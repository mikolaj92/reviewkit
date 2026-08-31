from collections.abc import Mapping

import pytest

from reviewkit import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewFinalityStatus,
    ReviewScope,
    assess_review_finality,
)


def _action(
    *,
    finding_id: str | None = "finding-1",
    action_type: ReviewActionType = ReviewActionType.INSERT_AFTER,
    status: ActionStatus = ActionStatus.APPLIED,
    apply_to_corrected: bool | None = True,
    category: str | None = "auto",
    requires_human_decision: bool = False,
    metadata: Mapping[str, object] | None = None,
) -> ReviewAction:
    return ReviewAction(
        finding_id=finding_id,
        scope=ReviewScope.PARAGRAPH,
        action_type=action_type,
        node_id="p1",
        original_text="anchor",
        replacement_text="replacement",
        status=status,
        apply_to_corrected=apply_to_corrected,
        category=category,
        requires_human_decision=requires_human_decision,
        metadata=dict(metadata or {}),
    )


def test_no_findings_is_final() -> None:
    assessment = assess_review_finality(finding_ids=[], actions=[])
    assert assessment.status is ReviewFinalityStatus.FINAL
    assert assessment.findings == 0


def test_applied_action_for_each_finding_is_final() -> None:
    assessment = assess_review_finality(finding_ids=["finding-1"], actions=[_action()])
    assert assessment.status is ReviewFinalityStatus.FINAL
    assert assessment.applied_edits == 1


def test_explicit_rejection_is_terminal() -> None:
    assessment = assess_review_finality(
        finding_ids=["finding-1"],
        actions=[_action(status=ActionStatus.NOT_APPLIED, apply_to_corrected=False)],
    )
    assert assessment.status is ReviewFinalityStatus.FINAL
    assert assessment.rejected_actions == 1


def test_missing_and_unexpected_finding_mapping_needs_review() -> None:
    assessment = assess_review_finality(
        finding_ids=["finding-1", "finding-2"],
        actions=[_action(finding_id="invented")],
    )
    assert assessment.status is ReviewFinalityStatus.NEEDS_REVIEW
    assert assessment.reason == "findings_without_applied_edits"


def test_unmapped_applied_edit_needs_review() -> None:
    assessment = assess_review_finality(finding_ids=[], actions=[_action(finding_id=None)])
    assert assessment.status is ReviewFinalityStatus.NEEDS_REVIEW
    assert assessment.reason == "applied_edits_without_finding_mapping"


@pytest.mark.parametrize("status", [ActionStatus.NEEDS_HUMAN_DECISION, ActionStatus.CONFLICT])
def test_unresolved_writing_action_needs_review(status: ActionStatus) -> None:
    assessment = assess_review_finality(finding_ids=["finding-1"], actions=[_action(status=status)])
    assert assessment.status is ReviewFinalityStatus.NEEDS_REVIEW
    assert assessment.reason == "unresolved_review_actions"


def test_policy_block_is_unresolved_not_rejected() -> None:
    assessment = assess_review_finality(
        finding_ids=["finding-1"],
        actions=[
            _action(
                status=ActionStatus.NOT_APPLIED,
                apply_to_corrected=False,
                metadata={"blocked_from_corrected": True},
            )
        ],
    )
    assert assessment.status is ReviewFinalityStatus.NEEDS_REVIEW
    assert assessment.unresolved_actions == 1
    assert assessment.rejected_actions == 0


def test_host_injected_suggestion_category_needs_review() -> None:
    assessment = assess_review_finality(
        finding_ids=[],
        actions=[
            _action(
                finding_id=None,
                action_type=ReviewActionType.COMMENT,
                status=ActionStatus.NOT_APPLIED,
                apply_to_corrected=False,
                category="host-suggestion",
            )
        ],
        suggested_categories=frozenset({"host-suggestion"}),
    )
    assert assessment.status is ReviewFinalityStatus.NEEDS_REVIEW
    assert assessment.reason == "suggested_actions_require_review"


def test_host_injected_manual_category_is_unresolved() -> None:
    assessment = assess_review_finality(
        finding_ids=["finding-1"],
        actions=[
            _action(
                action_type=ReviewActionType.RISK,
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                apply_to_corrected=False,
                category="host-manual",
            )
        ],
        unresolved_categories=frozenset({"host-manual"}),
    )
    assert assessment.status is ReviewFinalityStatus.NEEDS_REVIEW
    assert assessment.reason == "unresolved_review_actions"


@pytest.mark.parametrize("finding_ids", [[""], ["x", "x"], [" "]])
def test_invalid_finding_ids_fail_closed(finding_ids: list[str]) -> None:
    with pytest.raises(ValueError, match="unique non-empty"):
        assess_review_finality(finding_ids=finding_ids, actions=[])


def test_public_finality_api_is_exported() -> None:
    import reviewkit

    for name in (
        "ReviewFinalityAssessment",
        "ReviewFinalityStatus",
        "assess_review_finality",
    ):
        assert name in reviewkit.__all__

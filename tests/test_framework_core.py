import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from reviewkit.actions import (
    actions_for_paragraph,
    apply_corrections_to_text,
    prepare_actions,
    should_apply_to_corrected,
)
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewDimension,
    ReviewFinding,
    ReviewLocator,
    ReviewResult,
    ReviewScope,
    ReviewStats,
)
from reviewkit.profile import (
    ActionPolicyConfig,
    OutputConfig,
    ProtectedPatternConfig,
    ReviewProfile,
)


def test_extension_points_and_reference_mock_are_exported_from_package_root() -> None:
    import reviewkit
    from reviewkit import (
        LLMClient,
        MockLLMClient,
        ReviewContextProvider,
        ReviewDocument,
    )

    for name in ("LLMClient", "ReviewContextProvider", "MockLLMClient", "ReviewDocument"):
        assert name in reviewkit.__all__
    # MockLLMClient is the reference implementation of the LLMClient extension point.
    mock = MockLLMClient()
    assert hasattr(mock, "complete_json")
    assert LLMClient is not None
    assert ReviewContextProvider is not None
    assert ReviewDocument is not None


def test_profile_accepts_arbitrary_dimensions_and_conservative_defaults() -> None:
    profile = ReviewProfile.model_validate(
        {
            "profile_id": "custom-review",
            "display_name": "Custom Review",
            "description": "Caller-defined review profile.",
            "review_instructions": "Use only caller-provided criteria.",
            "review_dimensions": [
                "clarity",
                {
                    "id": "internal_policy",
                    "label": "Internal policy",
                    "metadata": {"owner": "ops"},
                },
            ],
            "name": "custom-review",
            "language": "en",
            "document_type": "caller-defined document",
            "reviewer_role": "caller-defined reviewer",
        }
    )

    assert profile.profile_id == "custom-review"
    assert profile.review_dimensions[0] == "clarity"
    dimension = profile.review_dimensions[1]
    assert isinstance(dimension, ReviewDimension)
    assert dimension.id == "internal_policy"
    assert dimension.metadata == {"owner": "ops"}

    policy = profile.resolved_action_policy()
    assert policy.require_llm_apply_hint is True
    assert policy.min_confidence_for_auto_apply == 0.85
    assert policy.max_severity_for_auto_apply == "medium"
    assert policy.auto_apply_requires_unique_match is True
    assert policy.auto_apply_sensitive_text is False
    assert policy.ambiguous_edit_behavior == "conflict"


def test_profile_rejects_unknown_keys_instead_of_silently_dropping_them() -> None:
    # Profiles are the only home for domain/safety rules, so a typo'd guard key must
    # surface loudly rather than silently keep the fail-closed default.
    base = {
        "name": "custom-review",
        "language": "en",
        "document_type": "caller-defined document",
        "reviewer_role": "caller-defined reviewer",
    }

    with pytest.raises(ValidationError, match="reviewer_roel"):
        ReviewProfile.model_validate({**base, "reviewer_roel": "typo"})

    with pytest.raises(ValidationError, match="require_llm_apply_hnt"):
        ReviewProfile.model_validate(
            {**base, "action_policy": {"require_llm_apply_hnt": True}}
        )

    with pytest.raises(ValidationError, match="preserv"):
        ProtectedPatternConfig.model_validate(
            {"name": "ref", "pattern": r"\[REF_\d+\]", "preserv": True}
        )

    with pytest.raises(ValidationError, match="corrected_docs"):
        OutputConfig.model_validate({"corrected_docs": False})


def test_findings_actions_and_result_json_are_separate(tmp_path: Path) -> None:
    finding = ReviewFinding(
        finding_id="finding-1",
        node_id="p1",
        title="Observation",
        description="Something worth reviewing.",
        dimension="clarity",
        severity="low",
        confidence=0.9,
        evidence=["example excerpt"],
        rationale="Caller-defined rationale.",
        metadata={"source": "rule"},
    )
    action = ReviewAction.model_validate(
        {
            "action_id": "action-1",
            "finding_id": "finding-1",
            "scope": ReviewScope.PARAGRAPH,
            "action_type": ReviewActionType.COMMENT,
            "node_id": "p1",
            "comment_text": "Consider revising this paragraph.",
            "confidence": 0.9,
        }
    )
    result = ReviewResult(
        findings=[finding],
        actions=[action],
        reviewed_docx=None,
        corrected_docx=None,
        document_summary=None,
        stats=ReviewStats.from_actions([action]),
    )

    report_path = tmp_path / "review.json"
    _ = result.save_json(report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["findings"][0]["finding_id"] == "finding-1"
    assert payload["actions"][0]["action_id"] == "action-1"
    assert payload["actions"][0]["finding_id"] == "finding-1"
    assert payload["actions"][0]["comment_text"] == "Consider revising this paragraph."
    assert payload["actions_by_type"] == {"comment": 1}


def test_report_exposes_needs_human_decision_escalation_queue(tmp_path: Path) -> None:
    def _action(status: ActionStatus, comment: str) -> ReviewAction:
        return ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.COMMENT,
            node_id="p1",
            comment=comment,
            status=status,
        )

    escalated = _action(ActionStatus.NEEDS_HUMAN_DECISION, "Ambiguous edit — decide.")
    result = ReviewResult(
        actions=[
            _action(ActionStatus.APPLIED, "Applied."),
            _action(ActionStatus.CONFLICT, "Conflicting."),
            escalated,
        ]
    )

    # The escalation queue is a first-class property, not something consumers hand-filter.
    assert result.needs_human_decision == [escalated]

    report_path = tmp_path / "review.json"
    _ = result.save_json(report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert [a["comment_text"] for a in payload["needs_human_decision"]] == ["Ambiguous edit — decide."]
    assert payload["actions_by_status"]["needs_human_decision"] == 1


def test_stale_locator_becomes_conflict_instead_of_silent_edit() -> None:
    document = _document("The cat sat.")
    profile = _auto_apply_profile()
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(
            node_id="p1",
            char_start=0,
            char_end=3,
            original_text="cat",
        ),
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.CONFLICT
    assert "locator" in (prepared[0].policy_reason or "")


def test_sensitive_text_edit_requires_human_decision_by_default() -> None:
    document = _document("The fee is 1000 PLN.")
    profile = _auto_apply_profile()
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="1000",
        replacement_text="2000",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(
            node_id="p1",
            char_start=11,
            char_end=15,
            original_text="1000",
        ),
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert prepared[0].metadata["blocked_from_corrected"] is True
    assert "sensitive text" in (prepared[0].policy_reason or "")


def test_guard_uses_the_real_locator_position_for_insert_after() -> None:
    # An INSERT_AFTER whose locator lands INSIDE a protected pattern breaks it. The guard
    # must score the text the canonical applier actually produces (insertion at char_end),
    # not a hand-rolled duplicate that appended at end-of-text and never saw the breakage.
    document = _document("See clause [REF_1] today.")
    profile = ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        action_policy=ActionPolicyConfig(
            apply_policy={"safe_edit": "apply"},
            require_llm_apply_hint=True,
            min_confidence_for_auto_apply=0.85,
            max_severity_for_auto_apply="medium",
            protected_patterns=[
                ProtectedPatternConfig(name="ref_marker", pattern=r"\[REF_\d+\]", preserve=True)
            ],
        ),
    )
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.INSERT_AFTER,
        node_id="p1",
        replacement_text=" NOTE",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        # char_end 15 sits between "[REF" and "_1]" — inserting here shatters the marker.
        locator=ReviewLocator(node_id="p1", char_start=11, char_end=15, original_text="[REF"),
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert prepared[0].metadata["blocked_from_corrected"] is True
    assert "Protected pattern" in (prepared[0].policy_reason or "")


def test_multiple_locator_edits_apply_from_original_offsets() -> None:
    document = _document("Alpha beta gamma.")
    profile = _auto_apply_profile()
    alpha = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="Alpha",
        replacement_text="A",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=0, char_end=5, original_text="Alpha"),
    )
    delete_beta = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.DELETE_TEXT,
        node_id="p1",
        original_text="beta",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=6, char_end=10, original_text="beta"),
    )
    before_beta = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.INSERT_BEFORE,
        node_id="p1",
        original_text="beta",
        replacement_text="small ",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=6, char_end=10, original_text="beta"),
    )
    after_gamma = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.INSERT_AFTER,
        node_id="p1",
        original_text="gamma",
        replacement_text="!",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=11, char_end=16, original_text="gamma"),
    )

    cases = [
        ([alpha, delete_beta, after_gamma], "A  gamma!."),
        ([alpha, before_beta, after_gamma], "A small beta gamma!."),
    ]
    for actions, expected in cases:
        for ordered_actions in (actions, list(reversed(actions))):
            prepared = prepare_actions(document, profile, ordered_actions)

            assert [action.status for action in prepared] == [ActionStatus.APPLIED] * len(actions)
            assert apply_corrections_to_text(document.text, prepared) == expected


def test_insert_after_orders_by_char_end_not_char_start() -> None:
    # INSERT_AFTER edits at char_end (a zero-width insertion), so the right-to-left sweep
    # must order it by char_end. Combined with a length-changing edit whose start sits
    # inside the insert's anchor span, ordering by char_start applied the edits out of
    # order (stale offset -> mislanded insertion) and also falsely demoted both as
    # "overlapping". Both orderings must now apply cleanly to the same result.
    document = _document("Alpha beta gamma.")
    profile = _auto_apply_profile()
    insert_after = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.INSERT_AFTER,
        node_id="p1",
        replacement_text=" X",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        # Anchor spans [1,10]; the insertion itself happens at char_end=10 (after "beta").
        locator=ReviewLocator(node_id="p1", char_start=1, char_end=10),
    )
    replace = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="bet",
        replacement_text="BETX",  # length-changing; its start (6) sits inside [1,10)
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=6, char_end=9, original_text="bet"),
    )

    for ordered_actions in ([insert_after, replace], [replace, insert_after]):
        prepared = prepare_actions(document, profile, ordered_actions)

        assert [action.status for action in prepared] == [
            ActionStatus.APPLIED,
            ActionStatus.APPLIED,
        ]
        assert apply_corrections_to_text(document.text, prepared) == "Alpha BETXa X gamma."


def test_non_unique_match_defaults_to_conflict() -> None:
    # auto_apply_requires_unique_match=True + ambiguous_edit_behavior="conflict" (defaults):
    # an ambiguous anchor is a CONFLICT, as before the flags were consulted.
    document = _document("kot i kot.")
    prepared = prepare_actions(document, _ambiguity_profile(), [_safe_replace("kot", "pies")])

    assert prepared[0].status == ActionStatus.CONFLICT
    assert "match exactly once" in (prepared[0].policy_reason or "")


def test_auto_apply_requires_unique_match_false_applies_first_occurrence() -> None:
    # With the guard disabled, a non-unique anchor no longer blocks auto-apply; the edit
    # lands on the first occurrence. Proves the flag is now honored (was dead config).
    document = _document("kot i kot.")
    profile = _ambiguity_profile(auto_apply_requires_unique_match=False)
    prepared = prepare_actions(document, profile, [_safe_replace("kot", "pies")])

    assert prepared[0].status == ActionStatus.APPLIED
    assert apply_corrections_to_text(document.text, prepared) == "pies i kot."


def test_ambiguous_edit_behavior_can_escalate_to_human_instead_of_conflict() -> None:
    # ambiguous_edit_behavior="needs_human_decision" routes an ambiguous edit to a human
    # rather than marking it a CONFLICT. Proves the field is now honored.
    document = _document("kot i kot.")
    profile = _ambiguity_profile(ambiguous_edit_behavior="needs_human_decision")
    prepared = prepare_actions(document, profile, [_safe_replace("kot", "pies")])

    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "match exactly once" in (prepared[0].policy_reason or "")


def test_comment_action_requiring_human_decision_is_not_downgraded() -> None:
    document = _document("This clause is unusual.")
    profile = _auto_apply_profile()
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        comment="Escalate this clause to a human reviewer.",
        requires_human_decision=True,
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION


def test_comment_action_without_human_decision_stays_advisory() -> None:
    document = _document("This clause is unusual.")
    profile = _auto_apply_profile()
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        comment="A minor stylistic note.",
        requires_human_decision=False,
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.NOT_APPLIED


def test_priority_vocabulary_is_caller_defined_not_hardcoded() -> None:
    document = _document("The cat sat.")
    profile = ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        action_policy=ActionPolicyConfig(
            apply_policy={"safe_edit": "apply"},
            require_llm_apply_hint=True,
            min_confidence_for_auto_apply=0.0,
            max_priority_for_auto_apply="routine",
            priority_order={"routine": 0, "urgent": 1},
        ),
    )
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        priority="urgent",
        locator=ReviewLocator(node_id="p1", char_start=4, char_end=7, original_text="cat"),
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "priority" in (prepared[0].policy_reason or "")


def test_action_type_keyed_policy_applies_when_category_has_no_rule() -> None:
    document = _document("The cat sat.")
    profile = ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        action_policy=ActionPolicyConfig(
            apply_policy={"replace_text": "apply"},
            require_llm_apply_hint=True,
            min_confidence_for_auto_apply=0.0,
        ),
    )
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="unmapped_category",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=4, char_end=7, original_text="cat"),
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.APPLIED
    assert apply_corrections_to_text(document.text, prepared) == "The dog sat."


def test_unknown_severity_fails_closed_past_the_max_severity_gate() -> None:
    document = _document("The cat sat.")
    profile = _auto_apply_profile()
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="safe_edit",
        severity="showstopper",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=4, char_end=7, original_text="cat"),
    )

    prepared = prepare_actions(document, profile, [action])

    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "severity" in (prepared[0].policy_reason or "")


def test_section_scoped_comment_attaches_to_a_single_paragraph() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                paragraphs=[
                    ParagraphNode(id="p1", text="The cat sat here.", section_id="s1"),
                    ParagraphNode(id="p2", text="The cat ran there.", section_id="s1"),
                ],
            )
        ]
    )
    comment = ReviewAction(
        scope=ReviewScope.SECTION,
        action_type=ReviewActionType.COMMENT,
        node_id="s1",
        original_text="cat",
        comment="Recurring subject worth a section note.",
    )

    p1_actions = actions_for_paragraph(document, document.sections[0].paragraphs[0], [comment])
    p2_actions = actions_for_paragraph(document, document.sections[0].paragraphs[1], [comment])

    attachments = [a for a in (*p1_actions, *p2_actions) if a.node_id == "s1"]
    assert len(attachments) == 1
    # Anchored to the first paragraph in the section that contains the quote.
    assert comment in p1_actions
    assert comment not in p2_actions


def test_scoped_comment_without_a_match_is_surfaced_not_dropped() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                paragraphs=[
                    ParagraphNode(id="p1", text="Alpha.", section_id="s1"),
                    ParagraphNode(id="p2", text="Beta.", section_id="s1"),
                ],
            )
        ]
    )
    comment = ReviewAction(
        scope=ReviewScope.SECTION,
        action_type=ReviewActionType.COMMENT,
        node_id="s1",
        original_text="gamma",
        comment="Note that never quotes matching text.",
    )

    p1_actions = actions_for_paragraph(document, document.sections[0].paragraphs[0], [comment])
    p2_actions = actions_for_paragraph(document, document.sections[0].paragraphs[1], [comment])

    attachments = [a for a in (*p1_actions, *p2_actions) if a.node_id == "s1"]
    assert len(attachments) == 1
    assert comment in p1_actions


def test_scope_level_edit_without_original_text_is_conflicted_not_falsely_applied() -> None:
    # A section/document-scoped writing action lacking original_text has no deterministic
    # paragraph anchor, so the corrected renderer would drop it while the stats claim it.
    # It must escalate to CONFLICT so should_apply_to_corrected and applied_count stay honest.
    document = _document("The cat sat here.")
    profile = _auto_apply_profile()
    scope_insert = ReviewAction(
        scope=ReviewScope.SECTION,
        action_type=ReviewActionType.INSERT_TEXT,
        node_id="s1",
        replacement_text=" A closing note.",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
    )

    prepared = prepare_actions(document, profile, [scope_insert])

    assert prepared[0].status == ActionStatus.CONFLICT
    assert "original_text" in (prepared[0].policy_reason or "")
    assert should_apply_to_corrected(prepared[0]) is False
    # And nothing routes it into a paragraph, so corrected.docx matches the (empty) set.
    paragraph = document.sections[0].paragraphs[0]
    assert actions_for_paragraph(document, paragraph, prepared) == []


def test_paragraph_level_insert_without_original_text_still_applies() -> None:
    # The scope-anchor guard is narrow: a paragraph-scoped insert (no original_text needed)
    # is directly applicable, so it must remain APPLIED and in the corrected set.
    document = _document("The cat sat here.")
    profile = _auto_apply_profile()
    paragraph_insert = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.INSERT_TEXT,
        node_id="p1",
        replacement_text=" A closing note.",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
    )

    prepared = prepare_actions(document, profile, [paragraph_insert])

    assert prepared[0].status == ActionStatus.APPLIED
    assert should_apply_to_corrected(prepared[0]) is True
    corrected = apply_corrections_to_text(document.get_node_text("p1") or "", prepared)
    assert corrected == "The cat sat here. A closing note."


def test_custom_severity_vocabulary_gates_auto_apply() -> None:
    # A non-standard severity scale must gate auto-apply when configured, instead of the
    # hardcoded English scale ranking every unknown severity above the threshold.
    document = _document("The cat sat here.")
    profile = ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        action_policy=ActionPolicyConfig(
            apply_policy={"safe_edit": "apply"},
            require_llm_apply_hint=True,
            min_confidence_for_auto_apply=0.85,
            severity_order={"trivial": 0, "notable": 1, "blocker": 2},
            max_severity_for_auto_apply="notable",
        ),
    )
    low = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="safe_edit",
        severity="trivial",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=4, char_end=7, original_text="cat"),
    )
    high = low.model_copy(update={"severity": "blocker"})

    prepared_low = prepare_actions(document, profile, [low])
    prepared_high = prepare_actions(document, profile, [high])

    assert prepared_low[0].status == ActionStatus.APPLIED
    assert prepared_high[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "severity" in (prepared_high[0].policy_reason or "")


def test_overlapping_edits_on_the_same_node_both_become_conflict() -> None:
    # Two edits validate fine in isolation but their char ranges overlap on "Alpha beta":
    # applying both would clobber one silently, so both must escalate to CONFLICT.
    document = _document("Alpha beta gamma.")
    profile = _auto_apply_profile()
    left = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="Alpha beta",
        replacement_text="X",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=0, char_end=10, original_text="Alpha beta"),
    )
    right = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="beta gamma",
        replacement_text="Y",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=6, char_end=16, original_text="beta gamma"),
    )

    prepared = prepare_actions(document, profile, [left, right])

    assert [action.status for action in prepared] == [
        ActionStatus.CONFLICT,
        ActionStatus.CONFLICT,
    ]
    assert all("overlapping edit range" in (action.policy_reason or "") for action in prepared)
    # Nothing overlapping leaks into the clean copy.
    assert apply_corrections_to_text(document.text, prepared) == document.text


def test_adjacent_non_overlapping_edits_still_both_apply() -> None:
    # Touching-but-not-overlapping ranges ([0,5] then [5,16]) are unambiguous; the
    # overlap guard must not demote them.
    document = _document("Alpha beta gamma.")
    profile = _auto_apply_profile()
    alpha = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="Alpha",
        replacement_text="A",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=0, char_end=5, original_text="Alpha"),
    )
    rest = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text=" beta gamma",
        replacement_text=" B",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=5, char_end=16, original_text=" beta gamma"),
    )

    prepared = prepare_actions(document, profile, [alpha, rest])

    assert [action.status for action in prepared] == [ActionStatus.APPLIED, ActionStatus.APPLIED]
    assert apply_corrections_to_text(document.text, prepared) == "A B."


def test_injected_action_policy_guard_escalates_an_otherwise_applied_edit() -> None:
    # A programmatic guard is the pluggable peer of regex protected_patterns: an edit
    # that clears every config gate must still escalate to a human when a caller-supplied
    # fail-closed guard objects, and must not leak into the clean copy.
    from reviewkit.policy import ActionPolicy

    document = _document("The cat sat here.")
    profile = _auto_apply_profile()
    calls: list[str] = []

    def _no_edits_touching_cat(action: ReviewAction, node_text: str) -> str | None:
        calls.append(action.node_id)
        if "cat" in (action.original_text or ""):
            return "guard: edits touching 'cat' need a human"
        return None

    policy = ActionPolicy.from_profile(profile, guards=[_no_edits_touching_cat])
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=4, char_end=7, original_text="cat"),
    )

    prepared = prepare_actions(document, profile, [action], policy=policy)

    assert calls == ["p1"]
    assert prepared[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "guard" in (prepared[0].policy_reason or "")
    assert apply_corrections_to_text(document.text, prepared) == document.text


def test_action_policy_without_guards_still_auto_applies() -> None:
    # Injecting a policy with no guards must behave exactly like the config-only default.
    from reviewkit.policy import ActionPolicy

    document = _document("The cat sat here.")
    profile = _auto_apply_profile()
    policy = ActionPolicy.from_profile(profile)
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="cat",
        replacement_text="dog",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=4, char_end=7, original_text="cat"),
    )

    prepared = prepare_actions(document, profile, [action], policy=policy)

    assert prepared[0].status == ActionStatus.APPLIED


def test_omitted_ids_are_derived_deterministically_from_content() -> None:
    # A uuid4 default made ids differ between identical runs, breaking report
    # reproducibility. Omitted ids must now be content-derived (stable + collision-safe
    # across distinct content), while an explicit id is preserved.
    first = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        comment="Same note.",
    )
    second = first.model_validate(first.model_dump())
    different = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        comment="Other note.",
    )
    explicit = ReviewAction(
        id="keep-me",
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        comment="Same note.",
    )

    assert first.id == second.id
    assert first.id != different.id
    assert first.id.startswith("action-")
    assert explicit.id == "keep-me"

    finding = ReviewFinding(node_id="p1", title="T", description="D")
    finding_again = ReviewFinding(node_id="p1", title="T", description="D")
    assert finding.finding_id == finding_again.finding_id
    assert finding.finding_id.startswith("finding-")
    assert (
        ReviewFinding(finding_id="fx", node_id="p1", title="T", description="D").finding_id == "fx"
    )


def _document(text: str) -> ReviewDocument:
    return ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                paragraphs=[ParagraphNode(id="p1", text=text, section_id="s1")],
            )
        ]
    )


def _auto_apply_profile() -> ReviewProfile:
    return ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        action_policy=ActionPolicyConfig(
            apply_policy={"safe_edit": "apply"},
            require_llm_apply_hint=True,
            min_confidence_for_auto_apply=0.85,
            max_severity_for_auto_apply="medium",
        ),
    )


def _ambiguity_profile(**policy_overrides: object) -> ReviewProfile:
    return ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        action_policy=ActionPolicyConfig(
            apply_policy={"safe_edit": "apply"},
            require_llm_apply_hint=True,
            min_confidence_for_auto_apply=0.85,
            max_severity_for_auto_apply="medium",
            **policy_overrides,
        ),
    )


def _safe_replace(original: str, replacement: str) -> ReviewAction:
    return ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text=original,
        replacement_text=replacement,
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
    )

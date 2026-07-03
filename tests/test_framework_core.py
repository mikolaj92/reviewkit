import json
from pathlib import Path

from reviewkit.actions import (
    actions_for_paragraph,
    apply_corrections_to_text,
    prepare_actions,
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
from reviewkit.profile import ActionPolicyConfig, ReviewProfile


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
    gamma = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE_TEXT,
        node_id="p1",
        original_text="gamma",
        replacement_text="G",
        category="safe_edit",
        confidence=1.0,
        apply_hint=True,
        locator=ReviewLocator(node_id="p1", char_start=11, char_end=16, original_text="gamma"),
    )

    for ordered_actions in ([alpha, gamma], [gamma, alpha]):
        prepared = prepare_actions(document, profile, ordered_actions)

        assert [action.status for action in prepared] == [ActionStatus.APPLIED, ActionStatus.APPLIED]
        assert apply_corrections_to_text(document.text, prepared) == "A beta G."


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

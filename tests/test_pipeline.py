from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from docx import Document as DocxDocument
from pack_support import silent_decision, silent_pack

from reviewkit import ReviewResult, parser_docx, review_document, review_tree
from reviewkit.context import ReviewContext, ReviewContextProvider
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.llm import MockLLMClient
from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewBoundError,
    ReviewFailureClass,
    ReviewFinding,
    ReviewScope,
)
from reviewkit.pipeline import _unresolved_finding_id_warnings
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState
from reviewkit.takt_reviewer import TaktReviewer

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def test_hierarchical_review_renders_prepared_actions(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "Ala ma kota.")
    reviewed_path = tmp_path / "reviewed.docx"
    corrected_path = tmp_path / "corrected.docx"
    extras = [
        ReviewAction.model_validate(
            {
                "id": "a-sentence",
                "scope": "sentence",
                "action_type": "replace",
                "node_id": "p1.s1",
                "original_text": "kota",
                "replacement_text": "psa",
                "reason": "Zmiana testowa.",
                "category": "typo",
                "confidence": 0.9,
                "apply_hint": True,
            }
        ),
        ReviewAction.model_validate(
            {
                "id": "a-paragraph",
                "scope": "paragraph",
                "action_type": "comment",
                "node_id": "p1",
                "comment": "Akapit jest zrozumiały.",
                "confidence": 0.8,
            }
        ),
        ReviewAction.model_validate(
            {
                "id": "a-section",
                "scope": "section",
                "action_type": "summary",
                "node_id": "s1",
                "comment": "Sekcja jest krótka.",
                "confidence": 0.8,
            }
        ),
    ]

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=reviewed_path,
        out_corrected=corrected_path,
        extra_actions=extras,
    )

    assert len(result.actions) == 3
    assert result.actions[0].status == ActionStatus.APPLIED
    assert result.document_summary is None


def test_review_tree_reviews_an_in_memory_document_without_rendering(tmp_path: Path) -> None:
    document = ReviewDocument(
        id="article",
        metadata={"source_format": "text"},
        sections=[
            SectionNode(
                id="s1",
                locator="text:section:0",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="The cat sat.",
                        section_id="s1",
                        locator="text:paragraph:0",
                        sentences=[
                            SentenceNode(
                                id="p1.s1",
                                text="The cat sat.",
                                paragraph_id="p1",
                                locator="text:paragraph:0:sentence:0",
                            )
                        ],
                    )
                ],
            )
        ],
    )

    result = review_tree(
        document=document,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
    )

    assert result.document is document
    assert result.document_summary is None
    assert result.artifacts == {}
    assert result.reviewed_docx is None
    assert result.corrected_docx is None
    assert not list(tmp_path.iterdir())


def test_review_document_accepts_a_review_profile_object(tmp_path: Path) -> None:
    # A caller that already holds a ReviewProfile (built in memory or cached) should not have
    # to round-trip it through a folder on disk. Passing the object directly must work exactly
    # like passing its folder path.
    from reviewkit.profile import load_profile

    input_path = _make_docx(tmp_path, "The cat sat.")
    profile = load_profile("examples/profiles/story.teacher")

    result = review_document(
        input_path=input_path,
        profile_path=profile,
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
    )

    assert isinstance(result, ReviewResult)
    assert result.document_summary is None


def test_overlapping_edits_from_different_scopes_both_escalate(tmp_path: Path) -> None:
    # A sentence-scope edit and a paragraph-scope edit each auto-apply in isolation - they
    # run in separate LLM responses, so prepare_actions never compares them. But both land
    # on paragraph p1 ("The cat" at [0,7] vs "cat sat" at [4,11] overlap), and applying both
    # would clobber one silently. The post-hierarchy cross-scope pass must escalate both.
    input_path = _make_docx(tmp_path, "The cat sat.")
    extras = [
        ReviewAction.model_validate(
            {
                "id": "a-sentence",
                "scope": "sentence",
                "action_type": "replace",
                "node_id": "p1.s1",
                "original_text": "The cat",
                "replacement_text": "A feline",
                "category": "typo",
                "confidence": 1.0,
                "apply_hint": True,
            }
        ),
        ReviewAction.model_validate(
            {
                "id": "a-paragraph",
                "scope": "paragraph",
                "action_type": "replace",
                "node_id": "p1",
                "original_text": "cat sat",
                "replacement_text": "dog ran",
                "category": "typo",
                "confidence": 1.0,
                "apply_hint": True,
            }
        ),
    ]

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=extras,
    )

    statuses = {action.id: action.status for action in result.actions}
    assert statuses["a-sentence"] == ActionStatus.CONFLICT
    assert statuses["a-paragraph"] == ActionStatus.CONFLICT
    # Neither clobbering edit reached the clean copy.
    assert _docx_text(result.corrected_docx) == "The cat sat."


def test_subset_pipeline_names_only_enabled_scopes() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                paragraphs=[
                    ParagraphNode(
                        id="p1",
                        text="The cat sat.",
                        section_id="s1",
                        sentences=[
                            SentenceNode(id="p1.s1", text="The cat sat.", paragraph_id="p1")
                        ],
                    )
                ],
            )
        ]
    )
    profile = ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.SENTENCE, ReviewScope.DOCUMENT],
    )
    decision = silent_decision()
    llm = _empty_llm()
    reviewer = TaktReviewer(profile=profile, llm=llm, pack=silent_pack(), decision=decision)
    reviewer.review(document)

    assert llm.calls == []
    assert len(decision.calls) == 2
    assert all(isinstance(call.state, str) for call in decision.calls)


def test_sentence_review_adds_action(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "confidence": 1.0,
        },
        text="To jest bład.",
    )

    assert len(result.actions) == 1
    assert result.actions[0].id == "a1"
    assert result.actions[0].action_type == ReviewActionType.REPLACE


def test_applied_actions_are_written_to_corrected_docx(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "confidence": 1.0,
            "apply_hint": True,
        },
        text="To jest bład.",
    )

    corrected_text = _docx_text(result.corrected_docx)
    assert "błąd" in corrected_text
    assert "bład" not in corrected_text


def test_suggestion_text_edits_are_tracked_in_reviewed_but_not_applied_in_corrected(
    tmp_path: Path,
) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bardzo",
            "replacement_text": "wyjątkowo",
            "category": "style",
            "confidence": 1.0,
        },
        text="To jest bardzo dobre.",
    )

    corrected_text = _docx_text(result.corrected_docx)
    reviewed_comments = _docx_comments(result.reviewed_docx)
    reviewed_xml = _docx_document_xml(result.reviewed_docx)
    assert "[DELETE:" not in reviewed_xml
    assert _revision_texts(result.reviewed_docx, "del", "delText") == ["bardzo"]
    assert _revision_texts(result.reviewed_docx, "ins", "t") == ["wyjątkowo"]
    assert "SUGGESTION" in reviewed_comments
    assert result.actions[0].status == ActionStatus.NOT_APPLIED
    assert "bardzo" in corrected_text
    assert "wyjątkowo" not in corrected_text


def test_conflict_is_not_applied(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "kot",
            "replacement_text": "pies",
            "category": "typo",
            "confidence": 1.0,
        },
        text="kot i kot.",
    )

    corrected_text = _docx_text(result.corrected_docx)
    assert result.actions[0].status == ActionStatus.CONFLICT
    assert "kot i kot." in corrected_text
    assert "pies" not in corrected_text


def test_document_type_action_policy_can_change_review_status(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "severity": "high",
            "confidence": 1.0,
            "apply_hint": True,
        },
        text="To jest bład.",
    )

    assert result.actions[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "exceeds policy threshold" in (result.actions[0].policy_reason or "")
    corrected_text = _docx_text(result.corrected_docx)
    assert "bład" in corrected_text
    assert "błąd" not in corrected_text


def test_policy_guard_blocks_corrected_when_protected_placeholder_changes(
    tmp_path: Path,
) -> None:
    input_path = _make_docx(tmp_path, "[OSOBA_1] podpisał umowę.")
    extra = ReviewAction.model_validate(
        {
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "[OSOBA_1]",
            "replacement_text": "Jan Kowalski",
            "category": "typo",
            "confidence": 1.0,
            "apply_to_corrected": True,
        }
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/employment-contract.lawyer",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )

    assert result.actions[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert result.actions[0].metadata["blocked_from_corrected"] is True
    corrected_text = _docx_text(result.corrected_docx)
    assert "[OSOBA_1] podpisał umowę." in corrected_text
    assert "Jan Kowalski" not in corrected_text


def test_pack_review_does_not_use_review_context_as_the_game(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "Ala ma kota.")
    decision = silent_decision()

    review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=decision,
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        context_provider=_StaticContextProvider(),
    )

    dumped = " ".join(_dump_state(call.state) for call in decision.calls)
    assert "Dike-style grounding" not in dumped
    assert "external_review_context" not in dumped


def test_tracked_revision_inputs_are_reported_as_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(parser_docx, "has_tracked_revisions", lambda path: True)

    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "comment",
            "node_id": "p1.s1",
            "comment": "Sprawdź historię zmian.",
            "confidence": 1.0,
        },
        text="To jest tekst.",
    )

    assert result.warnings == ["Input DOCX contains tracked revisions."]


def test_action_referencing_unknown_finding_id_is_reported_as_warning(tmp_path: Path) -> None:
    # The finding<->action linkage is the archetype's audit trail. An action pointing at a
    # finding_id no finding carries is a broken link and must surface as a warning; an action
    # whose finding_id resolves must not.
    input_path = _make_docx(tmp_path, "The cat sat.")
    extras = [
        ReviewAction.model_validate(
            {
                "id": "a-linked",
                "scope": "sentence",
                "action_type": "comment",
                "node_id": "p1.s1",
                "finding_id": "finding-real",
                "comment": "Responds to the finding.",
                "confidence": 0.9,
            }
        ),
        ReviewAction.model_validate(
            {
                "id": "a-dangling",
                "scope": "sentence",
                "action_type": "comment",
                "node_id": "p1.s1",
                "finding_id": "finding-ghost",
                "comment": "Points at a finding that does not exist.",
                "confidence": 0.9,
            }
        ),
    ]
    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=extras,
    )

    assert result.warnings == [
        "Action a-linked references unknown finding_id 'finding-real'.",
        "Action a-dangling references unknown finding_id 'finding-ghost'.",
    ]


def test_action_referencing_a_merged_away_finding_id_is_not_flagged() -> None:
    # When a duplicate finding is merged away, its finding_id is preserved on the survivor as
    # an alias, so an action that referenced the merged-away copy still resolves and must not
    # be reported as a dangling reference.
    survivor = ReviewFinding(
        finding_id="finding-a",
        node_id="p1",
        title="T",
        description="D",
        metadata={"merged_finding_ids": ["finding-b"]},
    )
    action = ReviewAction(
        id="a-1",
        scope=ReviewScope.SENTENCE,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        finding_id="finding-b",
        comment="Responds to the merged-away finding.",
    )

    assert _unresolved_finding_id_warnings([survivor], [action]) == []


def test_action_prompt_does_not_ask_the_writer_for_findings(tmp_path: Path) -> None:
    from reviewkit.pack import SourceUnit, Verdict, VerdictKind
    from reviewkit.profile import load_profile
    from reviewkit.prompts import action_prompt

    messages = action_prompt(
        load_profile("examples/profiles/story.teacher"),
        node_id="p1.s1",
        text="The cat sat.",
        verdict=Verdict(
            node_id="p1.s1", kind=VerdictKind.CHANGE, function_id="claim", reason="fix"
        ),
        unit=SourceUnit(id="u", source_id="s", locator="§1", text="sat", force="binding"),
    )
    assert messages[0]["role"] == "system"
    assert "Write the replacement this verdict asks for" in messages[0]["content"]
    assert "finding_id" not in messages[0]["content"]


def test_sentence_offset_edit_targets_the_correct_sentence(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "First sentence. Second sentence.")
    extra = ReviewAction.model_validate(
        {
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s2",
            "original_text": "Second",
            "replacement_text": "Next",
            "category": "typo",
            "confidence": 1.0,
            "apply_hint": True,
            "locator": {"char_start": 0, "char_end": 6},
        }
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )

    corrected_text = _docx_text(result.corrected_docx)
    assert result.actions[0].status == ActionStatus.APPLIED
    assert corrected_text == "First sentence. Next sentence."
    assert "Nextsentence" not in corrected_text


def test_sentence_string_edit_targets_the_matching_sentence(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "The cat sat. The cat ran.")
    extra = ReviewAction.model_validate(
        {
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s2",
            "original_text": "cat",
            "replacement_text": "dog",
            "category": "typo",
            "confidence": 1.0,
            "apply_hint": True,
        }
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )

    corrected_text = _docx_text(result.corrected_docx)
    assert result.actions[0].status == ActionStatus.APPLIED
    assert corrected_text == "The cat sat. The dog ran."


def test_plugin_error_aborts_on_first_decision_failure() -> None:
    class _RaisingDecision:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, state: object, questions: object) -> dict[str, bool]:
            self.calls += 1
            raise RuntimeError("simulated plugin failure")

    document = ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                paragraphs=[
                    ParagraphNode(id="p1", text="The cat sat.", section_id="s1"),
                    ParagraphNode(id="p2", text="The dog ran.", section_id="s1"),
                ],
            )
        ]
    )
    profile = ReviewProfile(
        name="generic",
        language="en",
        document_type="generic document",
        reviewer_role="generic reviewer",
        review_pipeline=[ReviewScope.PARAGRAPH],
    )

    decision = _RaisingDecision()
    reviewer = TaktReviewer(
        profile=profile, llm=_empty_llm(), pack=silent_pack(), decision=decision
    )

    with pytest.raises(ReviewBoundError, match="plugin_failure") as caught:
        reviewer.review(document)

    assert caught.value.failure_class is ReviewFailureClass.UNSUPPORTED_SHAPE
    assert decision.calls == 1


def test_identical_finding_surfaced_at_two_levels_appears_once() -> None:
    first = ReviewFinding(
        finding_id="dup-1",
        node_id="p1.s1",
        title="Repeated observation",
        description="The same issue seen at two levels.",
        dimension="clarity",
        severity="low",
    )
    second = ReviewFinding(
        finding_id="dup-1",
        node_id="p1",
        title="Repeated observation",
        description="The same issue seen at two levels.",
        dimension="clarity",
        severity="low",
    )
    state = ReviewState()
    state._add_findings([first])
    state._add_findings([second])
    assert [finding.finding_id for finding in state.findings] == ["dup-1"]


def test_report_records_policy_and_render_lineage_on_actions(tmp_path: Path) -> None:
    extra = ReviewAction.model_validate(
        {
            "id": "action-1",
            "scope": "sentence",
            "action_type": "comment",
            "node_id": "p1.s1",
            "comment": "Review wording.",
        }
    )
    result = review_document(
        input_path=_make_docx(tmp_path, "The cat sat."),
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )
    action_events = [event.model_dump(mode="json") for event in result.actions[0].lineage]
    assert any(
        event["kind"] == "policy" and event["decision"] == "not_applied" for event in action_events
    )
    assert {event["artifact"] for event in action_events if event["kind"] == "render"} == {
        "corrected_docx",
        "reviewed_docx",
    }


def test_review_document_threads_an_injected_action_policy(tmp_path: Path) -> None:
    # An edit that auto-applies with the profile's config-only policy must escalate once a
    # caller injects an ActionPolicy carrying a fail-closed guard -- proving review_document
    # threads the policy hook through to prepare_actions.
    from reviewkit.policy import ActionPolicy
    from reviewkit.profile import load_profile

    input_path = _make_docx(tmp_path, "To jest bład.")
    profile = load_profile("examples/profiles/story.teacher")

    def _block_all_writes(action, node_text):  # type: ignore[no-untyped-def]
        return "guard: no automatic writes in this run"

    policy = ActionPolicy.from_profile(profile, guards=[_block_all_writes])
    extra = ReviewAction.model_validate(
        {
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "confidence": 1.0,
            "apply_hint": True,
        }
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        action_policy=policy,
        extra_actions=[extra],
    )

    assert result.actions[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "guard" in (result.actions[0].policy_reason or "")
    # Escalated edits never reach the clean copy.
    assert "bład" in _docx_text(result.corrected_docx)


def test_identical_runs_produce_byte_identical_json_reports(tmp_path: Path) -> None:
    # A uuid4 default made every report unique even for identical input, defeating
    # diffing/caching. With content-derived ids two identical runs must serialize to
    # byte-identical JSON. The action and finding omit ids so the derivation is exercised.
    input_path = _make_docx(tmp_path, "To jest zdanie.")
    reviewed_path = tmp_path / "reviewed.docx"
    corrected_path = tmp_path / "corrected.docx"

    def _report(dest: Path) -> bytes:
        extra = ReviewAction.model_validate(
            {
                "scope": "sentence",
                "action_type": "comment",
                "node_id": "p1.s1",
                "comment": "Dobre zdanie.",
                "confidence": 0.9,
            }
        )
        result = review_document(
            input_path=input_path,
            profile_path="examples/profiles/story.teacher",
            llm=_empty_llm(),
            pack=silent_pack(),
            decision=silent_decision(),
            out_reviewed=reviewed_path,
            out_corrected=corrected_path,
            extra_actions=[extra],
        )
        return result.save_json(dest).read_bytes()

    assert _report(tmp_path / "a.json") == _report(tmp_path / "b.json")


def test_extra_action_is_tracked_in_reviewed_and_applied_in_corrected(tmp_path: Path) -> None:
    # A valid extra action (deterministic caller, no LLM involved) must flow through the same
    # machinery as reviewer output: validated, policy-checked, rendered as a tracked change in
    # reviewed.docx and applied in corrected.docx, with its source_system preserved.
    input_path = _make_docx(tmp_path, "To jest bład.")
    extra = ReviewAction(
        id="extra-1",
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE,
        node_id="p1",
        original_text="bład",
        replacement_text="błąd",
        category="typo",
        confidence=1.0,
        apply_hint=True,
        source_system="deterministic-checker",
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )

    assert [action.id for action in result.actions] == ["extra-1"]
    assert result.actions[0].status == ActionStatus.APPLIED
    assert result.actions[0].source_system == "deterministic-checker"
    assert _revision_texts(result.reviewed_docx, "del", "delText") == ["bład"]
    assert _revision_texts(result.reviewed_docx, "ins", "t") == ["błąd"]
    assert _docx_text(result.corrected_docx) == "To jest błąd."


def test_extra_action_overlapping_another_action_escalates_both(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "The cat sat.")
    extras = [
        ReviewAction(
            id="a-llm",
            scope=ReviewScope.SENTENCE,
            action_type=ReviewActionType.REPLACE,
            node_id="p1.s1",
            original_text="The cat",
            replacement_text="A feline",
            category="typo",
            confidence=1.0,
            apply_hint=True,
        ),
        ReviewAction(
            id="a-extra",
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.REPLACE,
            node_id="p1",
            original_text="cat sat",
            replacement_text="dog ran",
            category="typo",
            confidence=1.0,
            apply_hint=True,
            source_system="deterministic-checker",
        ),
    ]

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=extras,
    )

    statuses = {action.id: action.status for action in result.actions}
    assert statuses["a-llm"] == ActionStatus.CONFLICT
    assert statuses["a-extra"] == ActionStatus.CONFLICT
    extra_result = next(action for action in result.actions if action.id == "a-extra")
    assert extra_result.source_system == "deterministic-checker"
    # Neither clobbering edit reached the clean copy.
    assert _docx_text(result.corrected_docx) == "The cat sat."


def test_extra_action_with_unmatched_original_text_becomes_conflict(tmp_path: Path) -> None:
    # An extra action whose original_text does not exist in the document must surface as a
    # CONFLICT comment in reviewed.docx - never a silent apply - and leave corrected untouched.
    input_path = _make_docx(tmp_path, "To jest bład.")
    extra = ReviewAction(
        id="extra-ghost",
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE,
        node_id="p1",
        original_text="unicorn",
        replacement_text="horse",
        category="typo",
        confidence=1.0,
        apply_hint=True,
        source_system="deterministic-checker",
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )

    assert result.actions[0].status == ActionStatus.CONFLICT
    assert "found 0 matches" in (result.actions[0].policy_reason or "")
    comment_lines = _docx_comments(result.reviewed_docx).splitlines()
    assert any(line.startswith("CONFLICT:") for line in comment_lines), comment_lines
    assert _docx_text(result.corrected_docx) == "To jest bład."


def test_extra_actions_none_or_empty_matches_omitting_the_parameter(tmp_path: Path) -> None:
    # extra_actions=None (and []) must be byte-identical to today's behavior: same report
    # JSON and same reviewed/corrected artifacts as a call without the parameter.
    input_path = _make_docx(tmp_path, "To jest bład.")
    reviewed_path = tmp_path / "reviewed.docx"
    corrected_path = tmp_path / "corrected.docx"

    def _artifacts(suffix: str, **kwargs: Any) -> tuple[bytes, ...]:
        result = review_document(
            input_path=input_path,
            profile_path="examples/profiles/story.teacher",
            llm=_empty_llm(),
            pack=silent_pack(),
            decision=silent_decision(),
            out_reviewed=reviewed_path,
            out_corrected=corrected_path,
            **kwargs,
        )
        report = result.save_json(tmp_path / f"report-{suffix}.json").read_bytes()
        with ZipFile(reviewed_path) as archive:
            names = archive.namelist()
            reviewed = (
                archive.read("word/document.xml"),
                archive.read("word/comments.xml") if "word/comments.xml" in names else b"",
            )
        with ZipFile(corrected_path) as archive:
            corrected = archive.read("word/document.xml")
        return (report, *reviewed, corrected)

    baseline = _artifacts("baseline")
    assert _artifacts("none", extra_actions=None) == baseline
    assert _artifacts("empty", extra_actions=[]) == baseline


def _dump_state(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def _empty_llm() -> MockLLMClient:
    return MockLLMClient()


def _run_with_single_sentence_action(
    tmp_path: Path,
    action: dict[str, Any],
    text: str,
) -> ReviewResult:
    input_path = _make_docx(tmp_path, text)
    extra = ReviewAction.model_validate(action)
    return review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=_empty_llm(),
        pack=silent_pack(),
        decision=silent_decision(),
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        extra_actions=[extra],
    )


def _make_docx(tmp_path: Path, text: str) -> Path:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph(text)
    docx.save(input_path)
    return input_path


def _docx_text(path: Path | None) -> str:
    assert path is not None
    docx = DocxDocument(str(path))
    return "\n".join(paragraph.text for paragraph in docx.paragraphs)


def _docx_comments(path: Path | None) -> str:
    assert path is not None
    docx = DocxDocument(str(path))
    return "\n".join(comment.text for comment in docx.comments)


def _docx_document_xml(path: Path | None) -> str:
    assert path is not None
    with ZipFile(path) as archive:
        return archive.read("word/document.xml").decode()


def _revision_texts(path: Path | None, revision_tag: str, text_tag: str) -> list[str]:
    root = ElementTree.fromstring(_docx_document_xml(path))
    return [
        "".join(element.itertext())
        for element in root.findall(f".//{_W}{revision_tag}")
        if element.find(f".//{_W}{text_tag}") is not None
    ]


class _StaticContextProvider(ReviewContextProvider):
    def context_for(
        self,
        *,
        profile: ReviewProfile,
        document: ReviewDocument,
        state: ReviewState,
        scope,
        node,
    ) -> ReviewContext:
        return ReviewContext(
            scope=scope,
            node_id=node.id,
            data={"grounding": "Dike-style grounding", "source": "test"},
        )

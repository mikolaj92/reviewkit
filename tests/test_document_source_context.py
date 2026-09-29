from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from pack_support import silent_decision, silent_pack

from reviewkit.decision import DocumentDecisionState, MockDecisionClient
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.llm import MockLLMClient
from reviewkit.models import ReviewBoundError, ReviewFailureClass, ReviewScope
from reviewkit.pack import Function, Ontology, Pack, Rule, SourceUnit
from reviewkit.profile import ReviewProfile
from reviewkit.review_bounds import bound_document_sections, build_document_source_context
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import TaktDecision


def _profile(**overrides: object) -> ReviewProfile:
    payload: dict[str, object] = {
        "name": "generic-source-context",
        "language": "en",
        "document_type": "generic document",
        "reviewer_role": "generic reviewer",
        "review_pipeline": [ReviewScope.SECTION, ReviewScope.DOCUMENT],
        "section_char_budget": 80,
        "outputs": {"reviewed_docx": False, "corrected_docx": False},
    }
    payload.update(overrides)
    return ReviewProfile.model_validate(payload)


def _document(*, distant_clause: str = "A distant requirement is present.") -> ReviewDocument:
    paragraphs = [
        ParagraphNode(
            id=f"p{index}",
            text=(f"Local filler {index}. " * 4).strip(),
            section_id="s1",
            locator=f"body:p:{index}",
        )
        for index in range(8)
    ]
    paragraphs.append(
        ParagraphNode(
            id="p8",
            text=distant_clause,
            section_id="s1",
            locator="body:p:8",
        )
    )
    return ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                locator="body:section:0",
                paragraphs=paragraphs,
            )
        ]
    )


def _stable_takt_client() -> Mock:
    client = Mock()
    client.evaluate.return_value = TaktDecision(outcome="stable", node_id="node")
    return client


def _close_pack(
    *, locator: str = "body:p:8", text: str = "A distant requirement is present."
) -> Pack:
    return Pack(
        ontology=Ontology(
            functions=[
                Function(
                    id="requirement",
                    label="Requirement",
                    attach_to=["sentence", "paragraph", "section"],
                )
            ]
        ),
        units={
            "u": SourceUnit(
                id="u",
                source_id="s",
                locator=locator,
                text=text,
                force="binding",
            )
        },
        rules=[
            Rule(
                id="close",
                kind="close",
                function_id="requirement",
                scope="document",
                when="function_absent",
                source_unit_id="u",
            )
        ],
    )


def test_fragment_judge_never_asks_document_absence() -> None:
    decision = MockDecisionClient()
    reviewer = TaktReviewer(
        profile=_profile(),
        llm=MockLLMClient(),
        pack=_close_pack(),
        decision=decision,
        takt_client=_stable_takt_client(),
    )

    findings, _actions, state = reviewer.review(_document())

    fragment_calls = [call for call in decision.calls if "verdict" in call.questions]
    closing = [call for call in decision.calls if isinstance(call.state, DocumentDecisionState)]
    assert fragment_calls == []
    assert closing
    assert all("present" in call.questions for call in closing)
    assert "requirement" not in state.covered()
    assert [finding.title for finding in findings] == ["missing"]
    assert findings[0].description == "requirement"
    assert closing[0].state.unit is not None
    assert closing[0].state.unit.locator == "body:p:8"
    assert closing[0].state.unit.text == "A distant requirement is present."


def test_document_missing_comes_from_covered_gaps_not_fragment_text() -> None:
    decision = MockDecisionClient()
    reviewer = TaktReviewer(
        profile=_profile(),
        llm=MockLLMClient(),
        pack=_close_pack(),
        decision=decision,
        takt_client=_stable_takt_client(),
    )
    findings, _actions, state = reviewer.review(
        _document(distant_clause="An unrelated condition is present.")
    )

    assert "requirement" not in state.covered()
    assert any(item.title == "missing" for item in findings)
    closing = next(call for call in decision.calls if isinstance(call.state, DocumentDecisionState))
    assert closing.state.unit is not None
    assert closing.state.unit.locator == "body:p:8"


def test_named_function_skips_document_close() -> None:
    section_count = len(bound_document_sections(_document(), 80).sections)
    answers: list[dict[str, bool]] = [{"requirement": True}] + [{}] * section_count
    decision = MockDecisionClient(answers=answers)
    reviewer = TaktReviewer(
        profile=_profile(),
        llm=MockLLMClient(),
        pack=_close_pack(),
        decision=decision,
        takt_client=_stable_takt_client(),
    )
    findings, _actions, state = reviewer.review(_document())
    assert "requirement" in state.covered()
    assert not any(item.title == "missing" for item in findings)
    assert not any(isinstance(call.state, DocumentDecisionState) for call in decision.calls)


def test_document_source_budget_fails_before_any_plugin_call() -> None:
    llm = MockLLMClient()
    decision = silent_decision()
    reviewer = TaktReviewer(
        profile=_profile(document_source_char_budget=10),
        llm=llm,
        pack=silent_pack(),
        decision=decision,
        takt_client=_stable_takt_client(),
    )

    with pytest.raises(ReviewBoundError) as caught:
        reviewer.review(_document())

    assert caught.value.failure_class is ReviewFailureClass.OVERSIZE_UNIT
    assert caught.value.node_id == "document"
    assert not llm.calls
    assert decision.calls == []


def test_source_context_represents_title_only_and_empty_paragraph_shapes() -> None:
    document = ReviewDocument(
        sections=[
            SectionNode(id="title-only", title="A section heading", locator="body:heading:0"),
            SectionNode(
                id="body",
                paragraphs=[
                    ParagraphNode(
                        id="body-p0",
                        text="A body paragraph.",
                        section_id="body",
                        locator="body:p:0",
                    ),
                    ParagraphNode(
                        id="body-p1",
                        text="",
                        section_id="body",
                        locator="body:p:1",
                    ),
                ],
            ),
            SectionNode(id="empty", title="", locator="body:section:2"),
        ]
    )

    source = build_document_source_context(document, char_budget=4000)
    fragments = source["fragments"]
    projected_text = "\n\n".join(
        str(fragment["text"]) for fragment in fragments if str(fragment["text"]).strip()
    )
    assert projected_text == document.text
    assert {fragment["node_id"] for fragment in fragments} == {
        "title-only",
        "body-p0",
        "body-p1",
    }
    assert source["complete"] is True
    assert source["used"] == len(json.dumps(source, ensure_ascii=False, indent=2))

from __future__ import annotations

from unittest.mock import Mock

import pytest
from pack_support import silent_decision, silent_pack
from pydantic import BaseModel

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.llm import MockLLMClient
from reviewkit.models import ReviewBoundError, ReviewFailureClass, SectionReviewResponse
from reviewkit.pack import Function, Ontology, Pack, Rule
from reviewkit.profile import ReviewProfile
from reviewkit.review_bounds import bound_document_sections, validate_review_payload
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import TaktDecision


def _profile(**kwargs: object) -> ReviewProfile:
    payload = {
        "name": "generic",
        "language": "en",
        "document_type": "generic document",
        "reviewer_role": "generic reviewer",
        "review_pipeline": ["section"],
        "section_char_budget": 40,
        "outputs": {"reviewed_docx": False, "corrected_docx": False},
    }
    payload.update(kwargs)
    return ReviewProfile.model_validate(payload)


def _document(*paragraphs: str) -> ReviewDocument:
    nodes = [
        ParagraphNode(
            id=f"p{index}",
            text=text,
            section_id="s1",
            locator=f"body:p:{index}",
        )
        for index, text in enumerate(paragraphs)
    ]
    return ReviewDocument(sections=[SectionNode(id="s1", locator="body:p:0", paragraphs=nodes)])


def test_list_payload_is_unsupported_shape_not_section_response() -> None:
    with pytest.raises(ReviewBoundError) as caught:
        validate_review_payload(
            [{"title": "x"}],
            SectionReviewResponse,
            node_id="s1",
            budget=4096,
        )
    error = caught.value
    assert error.failure_class is ReviewFailureClass.UNSUPPORTED_SHAPE
    assert error.node_id == "s1"
    assert error.budget == 4096
    assert "list" in str(error)
    assert "title" not in str(error)


def test_object_payload_that_fails_schema_is_schema_mismatch() -> None:
    class _Required(BaseModel):
        findings: list[str]

    with pytest.raises(ReviewBoundError) as caught:
        validate_review_payload({"findings": "not-a-list"}, _Required, node_id="s1")
    assert caught.value.failure_class is ReviewFailureClass.SCHEMA_MISMATCH
    assert "not-a-list" not in str(caught.value)


def test_mock_client_timeout_marker_is_typed_timeout() -> None:
    client = MockLLMClient(responses=["timeout"])
    with pytest.raises(ReviewBoundError) as caught:
        client.complete_json(
            [{"role": "user", "content": '{"current_fragment": {"node_id": "s1"}}'}],
            SectionReviewResponse,
        )
    assert caught.value.failure_class is ReviewFailureClass.TIMEOUT
    assert caught.value.node_id == "s1"


def test_oversized_section_splits_at_paragraph_locators() -> None:
    document = _document("aaaa", "bbbb", "cccc")
    bounded = bound_document_sections(document, char_budget=10)
    assert [section.id for section in bounded.sections] == ["s1:chunk:0", "s1:chunk:1"]
    assert [p.locator for section in bounded.sections for p in section.paragraphs] == [
        "body:p:0",
        "body:p:1",
        "body:p:2",
    ]
    assert bounded.sections[0].locator == "body:p:0"
    assert bounded.sections[1].locator == "body:p:2"


def test_single_paragraph_over_budget_fails_closed() -> None:
    document = _document("this paragraph is longer than the budget")
    with pytest.raises(ReviewBoundError) as caught:
        bound_document_sections(document, char_budget=8)
    assert caught.value.failure_class is ReviewFailureClass.OVERSIZE_UNIT
    assert caught.value.node_id == "p0"
    assert "this paragraph" not in str(caught.value)


def test_reviewer_does_not_publish_partial_actions_on_schema_failure() -> None:
    from reviewkit.decision import MockDecisionClient

    document = _document("short")
    pack = Pack(
        ontology=Ontology(
            functions=[
                Function(id="claim", label="Claim", attach_to=["sentence", "paragraph", "section"])
            ]
        ),
        units={},
        rules=[
            Rule(
                id="defect",
                kind="defect",
                function_id="claim",
                scope="fragment",
                when="function_present",
            )
        ],
    )
    decision = MockDecisionClient(answers=[{"claim": True}, {"verdict": "change"}])
    llm = MockLLMClient(responses=[[{"title": "not-an-object"}]])
    takt = Mock()
    takt.evaluate.return_value = TaktDecision(outcome="stable", node_id="s1")
    reviewer = TaktReviewer(
        profile=_profile(section_char_budget=4000),
        llm=llm,
        pack=pack,
        decision=decision,
        takt_client=takt,
    )
    findings, actions, state = reviewer.review(document)
    assert [finding.title for finding in findings] == ["change"]
    assert actions[0].requires_human_decision is True
    assert actions[0].replacement_text is None
    assert llm.calls
    assert len(llm.calls) == 1
    assert any("plugin_failure" in warning for warning in state.warnings)


def test_split_sections_preserve_order_and_keep_review_deterministic() -> None:
    document = _document("aaaa", "bbbb")
    decision = silent_decision()
    reviewer = TaktReviewer(
        profile=_profile(section_char_budget=6),
        llm=MockLLMClient(),
        pack=silent_pack(),
        decision=decision,
    )
    findings, actions, _state = reviewer.review(document)
    assert findings == []
    assert actions == []
    assert len(decision.calls) == 2
    assert all(isinstance(call.state, str) for call in decision.calls)

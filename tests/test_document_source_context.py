from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.llm import MockLLMClient
from reviewkit.models import (
    DocumentReviewResponse,
    ReviewBoundError,
    ReviewFailureClass,
    ReviewScope,
    SectionReviewResponse,
)
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


def test_document_prompt_contains_complete_source_fragments() -> None:
    llm = MockLLMClient()
    reviewer = TaktReviewer(
        profile=_profile(),
        llm=llm,
        takt_client=_stable_takt_client(),
    )

    reviewer.review(_document())

    section_call = next(call for call in llm.calls if call.schema is SectionReviewResponse)
    document_call = next(call for call in llm.calls if call.schema is DocumentReviewResponse)
    assert '"document_wide_absence": "unsupported"' in section_call.content
    assert "does not establish document-wide absence" in section_call.content
    assert "A distant requirement is present." in document_call.content
    assert "body:p:8" in document_call.content
    assert '"complete": true' in document_call.content


def _document_response(
    *,
    finding_id: str,
    title: str,
    description: str,
    evidence_locator: str | None,
    action: bool = True,
) -> dict[str, object]:
    finding: dict[str, object] = {
        "finding_id": finding_id,
        "node_id": "document",
        "title": title,
        "description": description,
        "severity": "high",
        "confidence": 0.9,
    }
    if evidence_locator is not None:
        finding["evidence"] = [{"locator": evidence_locator}]
    response: dict[str, object] = {"findings": [finding], "summary": "document checked"}
    if action:
        response["actions"] = [
            {
                "id": f"action-{finding_id}",
                "finding_id": finding_id,
                "scope": "document",
                "action_type": "comment",
                "node_id": "document",
                "comment": "Review this requirement.",
                "confidence": 0.9,
                "evidence_refs": ([{"locator": evidence_locator}] if evidence_locator else []),
            }
        ]
    return response


def _review_with_document_response(
    response: dict[str, object],
    *,
    document: ReviewDocument | None = None,
    section_responses: list[dict[str, object]] | None = None,
    **profile_overrides: object,
) -> tuple[list[object], list[object], MockLLMClient]:
    document = document or _document()
    profile = _profile(**profile_overrides)
    section_count = len(bound_document_sections(document, profile.section_char_budget).sections)
    scripted_sections = section_responses or [{"summary": "section checked"}] * section_count
    assert len(scripted_sections) == section_count
    llm = MockLLMClient(responses=[*scripted_sections, response])
    reviewer = TaktReviewer(
        profile=profile,
        llm=llm,
        takt_client=_stable_takt_client(),
    )
    findings, actions, _state = reviewer.review(document)
    return findings, actions, llm


def test_document_response_preserves_distant_locator_in_findings_and_actions() -> None:
    findings, actions, llm = _review_with_document_response(
        _document_response(
            finding_id="distant-defect",
            title="Distant requirement",
            description="The requirement is present in a distant source fragment.",
            evidence_locator="body:p:8",
        )
    )

    finding = next(item for item in findings if item.finding_id == "distant-defect")
    assert finding.evidence[0].locator == "body:p:8"
    action = next(item for item in actions if item.id == "action-distant-defect")
    assert action.finding_id == "distant-defect"
    assert action.evidence_refs[0].locator == "body:p:8"
    assert any(call.schema is DocumentReviewResponse for call in llm.calls)


def test_document_response_keeps_true_absence_finding() -> None:
    target = "A distant requirement is present."
    findings, _actions, llm = _review_with_document_response(
        _document_response(
            finding_id="missing-requirement",
            title="Requirement absent",
            description="The source contains no such requirement.",
            evidence_locator=None,
            action=False,
        ),
        document=_document(distant_clause="An unrelated condition is present."),
    )

    assert any(item.finding_id == "missing-requirement" for item in findings)
    document_call = next(call for call in llm.calls if call.schema is DocumentReviewResponse)
    assert target not in document_call.content


def test_document_response_keeps_distinct_defect_when_distant_clause_is_present() -> None:
    section_defect = {
        "findings": [
            {
                "finding_id": "local-defect",
                "node_id": "s1:chunk:0",
                "title": "Local defect",
                "description": "A separate local problem was observed.",
                "severity": "medium",
                "confidence": 0.8,
            }
        ],
        "summary": "section checked",
    }
    document = _document()
    section_count = len(bound_document_sections(document, 80).sections)
    findings, _actions, _llm = _review_with_document_response(
        _document_response(
            finding_id="distant-clause-defect",
            title="Distant requirement is defective",
            description="The distant requirement is present but incomplete.",
            evidence_locator="body:p:8",
            action=False,
        ),
        document=document,
        section_responses=[section_defect] + [{"summary": "section checked"}] * (section_count - 1),
    )

    assert any(item.finding_id == "local-defect" for item in findings)
    finding = next(item for item in findings if item.finding_id == "distant-clause-defect")
    assert finding.evidence[0].locator == "body:p:8"


def test_document_source_budget_fails_before_any_model_call() -> None:
    llm = MockLLMClient()
    reviewer = TaktReviewer(
        profile=_profile(document_source_char_budget=10),
        llm=llm,
        takt_client=_stable_takt_client(),
    )

    with pytest.raises(ReviewBoundError) as caught:
        reviewer.review(_document())

    assert caught.value.failure_class is ReviewFailureClass.OVERSIZE_UNIT
    assert caught.value.node_id == "document"
    assert not llm.calls


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
        str(fragment["text"])
        for fragment in fragments
        if str(fragment["text"]).strip()
    )
    assert projected_text == document.text
    assert {fragment["node_id"] for fragment in fragments} == {
        "title-only",
        "body-p0",
        "body-p1",
    }
    assert source["complete"] is True
    assert source["used"] == len(json.dumps(source, ensure_ascii=False, indent=2))


def test_complete_source_is_sent_once_to_document_scope_only() -> None:
    _findings, _actions, llm = _review_with_document_response(
        _document_response(
            finding_id="source-only-document",
            title="Source context check",
            description="Document scope received the complete source.",
            evidence_locator="body:p:8",
            action=False,
        )
    )

    section_calls = [call for call in llm.calls if call.schema is SectionReviewResponse]
    document_call = next(call for call in llm.calls if call.schema is DocumentReviewResponse)
    assert section_calls
    assert "A distant requirement is present." not in section_calls[0].content
    assert all("source_document" not in call.content for call in section_calls)
    assert "source_document" in document_call.content


def test_document_scope_keeps_lower_scope_actions_with_source_context() -> None:
    document = _document()
    section_count = len(bound_document_sections(document, 80).sections)
    lower_action = {
        "actions": [
            {
                "id": "lower-action",
                "scope": "section",
                "action_type": "comment",
                "node_id": "s1:chunk:0",
                "comment": "A local observation.",
                "confidence": 0.8,
            }
        ],
        "summary": "section checked",
    }
    _findings, actions, llm = _review_with_document_response(
        _document_response(
            finding_id="document-action",
            title="Document observation",
            description="A document-level observation.",
            evidence_locator="body:p:8",
        ),
        document=document,
        section_responses=[lower_action] + [{"summary": "section checked"}] * (section_count - 1),
    )

    document_call = next(call for call in llm.calls if call.schema is DocumentReviewResponse)
    assert "lower-action" in document_call.content
    assert {action.id for action in actions} >= {"lower-action", "action-document-action"}

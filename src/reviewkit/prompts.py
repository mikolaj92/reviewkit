"""Prompt builders for each review level."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from reviewkit.context import ReviewContext
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.models import (
    DocumentReviewResponse,
    ParagraphReviewResponse,
    ReconciliationRequest,
    ReviewAction,
    SectionReviewResponse,
    SentenceReviewResponse,
)
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState


def sentence_review_prompt(
    profile: ReviewProfile,
    state: ReviewState,
    sentence: SentenceNode,
    context: ReviewContext | None = None,
) -> list[dict[str, str]]:
    payload = {
        "review_level": "sentence",
        "current_fragment": {"node_id": sentence.id, "text": sentence.text},
        "source_scope": _fragment_scope_payload(),
        "external_review_context": _context_payload(context),
        "current_review_state": _state_payload(state),
        "schema": SentenceReviewResponse.model_json_schema(),
    }
    return _messages(profile, payload)


def paragraph_review_prompt(
    profile: ReviewProfile,
    state: ReviewState,
    paragraph: ParagraphNode,
    sentence_actions: list[ReviewAction],
    context: ReviewContext | None = None,
) -> list[dict[str, str]]:
    payload = {
        "review_level": "paragraph",
        "current_fragment": {"node_id": paragraph.id, "text": paragraph.text},
        "source_scope": _fragment_scope_payload(),
        "sentence_review_results": _actions_payload(sentence_actions),
        "external_review_context": _context_payload(context),
        "current_review_state": _state_payload(state),
        "schema": ParagraphReviewResponse.model_json_schema(),
    }
    return _messages(profile, payload)


def section_review_prompt(
    profile: ReviewProfile,
    state: ReviewState,
    section: SectionNode,
    paragraph_actions: list[ReviewAction],
    context: ReviewContext | None = None,
) -> list[dict[str, str]]:
    payload = {
        "review_level": "section",
        "current_fragment": {
            "node_id": section.id,
            "title": section.title,
            "text": section.text,
        },
        "source_scope": _fragment_scope_payload(),
        "paragraph_review_results": _actions_payload(paragraph_actions),
        "external_review_context": _context_payload(context),
        "current_review_state": _state_payload(state),
        "schema": SectionReviewResponse.model_json_schema(),
    }
    return _messages(profile, payload)


def document_review_prompt(
    profile: ReviewProfile,
    state: ReviewState,
    document: ReviewDocument,
    section_actions: list[ReviewAction],
    context: ReviewContext | None = None,
    source_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    payload = {
        "review_level": "document",
        "current_fragment": {
            "node_id": document.id,
            "section_count": len(document.sections),
        },
        "source_scope": _document_scope_payload(source_context),
        "source_document": source_context or {"complete": False},
        "section_summaries": state.section_summaries,
        "all_risks": state.risks,
        "all_questions": state.questions,
        "missing_elements": state.missing_elements,
        "repeated_issues": state.repeated_issues,
        "section_review_results": _actions_payload(section_actions),
        "external_review_context": _context_payload(context),
        "current_review_state": _state_payload(state),
        "schema": DocumentReviewResponse.model_json_schema(),
    }
    return _messages(profile, payload)


def reconciliation_review_prompt(
    profile: ReviewProfile,
    state: ReviewState,
    target: SentenceNode | ParagraphNode | SectionNode,
    request: ReconciliationRequest,
    document_summary: str | None,
) -> list[dict[str, str]]:
    """Build a rereview prompt whose routing was already fixed by the host."""
    payload = {
        "review_level": "reconciliation",
        "current_fragment": {"node_id": target.id, "text": target.text},
        "whole_document_summary": document_summary,
        "reconciliation_request": request.model_dump(mode="json"),
        "current_review_state": _state_payload(state),
        "schema": SentenceReviewResponse.model_json_schema(),
    }
    return _messages(profile, payload)


def _messages(profile: ReviewProfile, payload: dict[str, Any]) -> list[dict[str, str]]:
    payload = {"review_profile": _profile_payload(profile), **payload}
    system = (
        f"You are acting as: {profile.reviewer_role}.\n"
        f"Document type: {profile.document_type}.\n"
        f"Language: {profile.language}.\n\n"
        "Review the document like a human reviewer. Do not rewrite the whole document. "
        "Return findings separately from actions. Target actions with node_id values and "
        "original_text snippets. Include locators only when exact current text coordinates "
        "are known.\n"
        "Always emit an explicit finding_id on every finding, and when an action responds "
        "to a finding, set that action's finding_id to the same value so the response can be "
        "traced back to what motivated it.\n\n"
        f"Profile instructions:\n{profile.instructions_text}"
    )
    if payload.get("review_level") == "document":
        system = (
            f"{system}\n\nDocument source contract: make document-wide absence claims only when "
            "source_document.complete is true. Cite source fragment locators for observed "
            "presence or defects."
        )
    elif payload.get("review_level") in {"sentence", "paragraph", "section"}:
        system = (
            f"{system}\n\nFragment source contract: current_fragment is bounded local evidence. "
            "Its missing text does not establish document-wide absence; report only local "
            "observations with their evidence."
        )
    user = (
        "Return JSON only, valid against the included Pydantic JSON schema.\n"
        "The engine will deterministically verify and apply actions later.\n\n"
        f"{_json(payload)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _state_payload(state: ReviewState) -> dict[str, Any]:
    # ``warnings`` are engine-internal diagnostics (malformed model output that was
    # dropped, action-processing errors); they are not review substance. Feeding
    # them back into the next level's prompt only adds noise and risks the model
    # reacting to our own bookkeeping, so exclude them from the state it sees.
    return state.model_dump(mode="json", exclude={"warnings"})


def _actions_payload(actions: list[ReviewAction]) -> list[dict[str, Any]]:
    return [action.model_dump(mode="json", by_alias=True) for action in actions]


def _profile_payload(profile: ReviewProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "display_name": profile.display_name,
        "description": profile.description,
        "language": profile.language,
        "document_type": profile.document_type,
        "reviewer_role": profile.reviewer_role,
        "review_dimensions": [
            _dimension_payload(dimension) for dimension in profile.review_dimensions
        ],
        "action_policy": profile.resolved_action_policy().model_dump(mode="json"),
    }


def _dimension_payload(dimension: str | BaseModel) -> dict[str, Any]:
    if isinstance(dimension, BaseModel):
        return dimension.model_dump(mode="json")
    return {"id": dimension, "label": dimension}


def _context_payload(context: ReviewContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return context.model_dump(mode="json")


def _fragment_scope_payload() -> dict[str, Any]:
    return {
        "scope": "fragment",
        "complete": False,
        "document_wide_absence": "unsupported",
    }


def _document_scope_payload(source_context: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "scope": "document",
        "complete": bool(source_context and source_context.get("complete")),
    }


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)

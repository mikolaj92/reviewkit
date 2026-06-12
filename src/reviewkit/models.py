"""Core data models used by the review engine."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ReviewScope(StrEnum):
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    SECTION = "section"
    DOCUMENT = "document"


class ReviewActionType(StrEnum):
    REPLACE = "replace"
    DELETE = "delete"
    INSERT_BEFORE = "insert_before"
    INSERT_AFTER = "insert_after"
    COMMENT = "comment"
    QUESTION = "question"
    RISK = "risk"
    SUGGESTION = "suggestion"
    PRAISE = "praise"
    SUMMARY = "summary"


class ActionStatus(StrEnum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    NEEDS_HUMAN_DECISION = "needs_human_decision"
    CONFLICT = "conflict"


class EvidenceRef(BaseModel):
    segment_id: str | None = None
    locator: str | None = None
    excerpt: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewReference(BaseModel):
    source: str
    label: str | None = None
    url: str | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewAction(BaseModel):
    id: str = Field(default_factory=lambda: f"action-{uuid4().hex}")
    scope: ReviewScope
    action_type: ReviewActionType
    node_id: str
    original_text: str | None = None
    replacement_text: str | None = None
    comment: str | None = None
    reason: str | None = None
    severity: str = "medium"
    status: ActionStatus = ActionStatus.NOT_APPLIED
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    category: str | None = None
    priority: str | None = None
    requires_human_decision: bool = False
    apply_to_corrected: bool | None = None
    policy_reason: str | None = None
    source_system: str | None = None
    tags: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    references: list[ReviewReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewResponse(BaseModel):
    actions: list[ReviewAction] = Field(default_factory=list)
    summary: str | None = None
    repeated_issues: list[str] = Field(default_factory=list)
    style_observations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    human_decisions: list[str] = Field(default_factory=list)


class SentenceReviewResponse(ReviewResponse):
    pass


class ParagraphReviewResponse(ReviewResponse):
    pass


class SectionReviewResponse(ReviewResponse):
    pass


class DocumentReviewResponse(ReviewResponse):
    pass


class ReviewStats(BaseModel):
    applied_count: int = 0
    suggestion_count: int = 0
    risk_count: int = 0
    conflict_count: int = 0
    human_decision_count: int = 0

    @classmethod
    def from_actions(cls, actions: list[ReviewAction]) -> "ReviewStats":
        return cls(
            applied_count=sum(action.status == ActionStatus.APPLIED for action in actions),
            suggestion_count=sum(
                action.action_type == ReviewActionType.SUGGESTION for action in actions
            ),
            risk_count=sum(action.action_type == ReviewActionType.RISK for action in actions),
            conflict_count=sum(action.status == ActionStatus.CONFLICT for action in actions),
            human_decision_count=sum(
                action.status == ActionStatus.NEEDS_HUMAN_DECISION for action in actions
            ),
        )


class ReviewResult(BaseModel):
    actions: list[ReviewAction]
    reviewed_docx: Path | None
    corrected_docx: Path | None
    document_summary: str | None
    stats: ReviewStats

"""Core data models used by the review engine."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class ReviewScope(StrEnum):
    SENTENCE = "sentence"
    PARAGRAPH = "paragraph"
    SECTION = "section"
    DOCUMENT = "document"


class ReviewActionType(StrEnum):
    COMMENT = "comment"
    REPLACE_TEXT = "replace_text"
    INSERT_TEXT = "insert_text"
    DELETE_TEXT = "delete_text"
    FLAG = "flag"
    NOOP = "noop"

    REPLACE = "replace"
    DELETE = "delete"
    INSERT_BEFORE = "insert_before"
    INSERT_AFTER = "insert_after"
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


class ReviewDimension(BaseModel):
    id: str
    label: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewLocator(BaseModel):
    node_id: str | None = None
    paragraph_index: int | None = None
    sentence_index: int | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    original_text: str | None = None
    context_before: str | None = None
    context_after: str | None = None
    text_hash: str | None = None
    node_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ReviewFinding(BaseModel):
    finding_id: str = ""
    node_id: str
    title: str
    description: str
    dimension: str | ReviewDimension | None = None
    severity: str = "medium"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str | EvidenceRef] = Field(default_factory=list)
    rationale: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_finding_id(self) -> "ReviewFinding":
        # Derive omitted ids deterministically from content so identical LLM output
        # yields identical ids across runs (a uuid4 default broke report reproducibility
        # and made any referenced finding_id unstable). An explicit id is preserved.
        if not self.finding_id:
            self.finding_id = _stable_id(
                "finding",
                [self.node_id, self.title, self.description, _dimension_key(self.dimension),
                 self.severity],
            )
        return self


class ReviewAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(
        default="",
        validation_alias=AliasChoices("id", "action_id"),
        serialization_alias="action_id",
    )
    finding_id: str | None = None
    scope: ReviewScope
    action_type: ReviewActionType
    node_id: str
    original_text: str | None = None
    replacement_text: str | None = None
    comment: str | None = Field(
        default=None,
        validation_alias=AliasChoices("comment", "comment_text"),
        serialization_alias="comment_text",
    )
    reason: str | None = None
    severity: str = "medium"
    status: ActionStatus = ActionStatus.NOT_APPLIED
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    category: str | None = None
    priority: str | None = None
    requires_human_decision: bool = False
    apply_hint: bool | None = None
    apply_to_corrected: bool | None = None
    locator: ReviewLocator | None = None
    policy_reason: str | None = None
    source_system: str | None = None
    tags: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    references: list[ReviewReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_action_id(self) -> "ReviewAction":
        # Deterministic content-derived id for omitted ids (see ReviewFinding); an
        # explicit id/action_id from the model is preserved unchanged.
        if not self.id:
            self.id = _stable_id(
                "action",
                [self.node_id, self.scope, self.action_type, self.original_text,
                 self.replacement_text, self.comment],
            )
        return self

    @property
    def action_id(self) -> str:
        return self.id

    @property
    def comment_text(self) -> str | None:
        return self.comment


class ReviewResponse(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
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
    document: Any | None = None
    findings: list[ReviewFinding] = Field(default_factory=list)
    actions: list[ReviewAction] = Field(default_factory=list)
    reviewed_docx: Path | None = None
    corrected_docx: Path | None = None
    document_summary: str | None = None
    stats: ReviewStats = Field(default_factory=ReviewStats)
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)

    @property
    def applied_actions(self) -> list[ReviewAction]:
        return [action for action in self.actions if action.status == ActionStatus.APPLIED]

    @property
    def skipped_actions(self) -> list[ReviewAction]:
        return [action for action in self.actions if action.status == ActionStatus.NOT_APPLIED]

    @property
    def conflicts(self) -> list[ReviewAction]:
        return [action for action in self.actions if action.status == ActionStatus.CONFLICT]

    def to_report_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", by_alias=True, exclude={"document"})
        payload["applied_actions"] = [
            action.model_dump(mode="json", by_alias=True) for action in self.applied_actions
        ]
        payload["skipped_actions"] = [
            action.model_dump(mode="json", by_alias=True) for action in self.skipped_actions
        ]
        payload["conflicts"] = [
            action.model_dump(mode="json", by_alias=True) for action in self.conflicts
        ]
        payload["findings_by_dimension"] = dict(
            Counter(_dimension_key(finding.dimension) for finding in self.findings)
        )
        payload["findings_by_severity"] = dict(
            Counter(finding.severity for finding in self.findings)
        )
        payload["actions_by_type"] = dict(
            Counter(action.action_type.value for action in self.actions)
        )
        payload["actions_by_status"] = dict(Counter(action.status.value for action in self.actions))
        return payload

    def save_json(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _ = output_path.write_text(
            json.dumps(self.to_report_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path


def _dimension_key(dimension: str | ReviewDimension | None) -> str:
    if dimension is None:
        return "uncategorized"
    if isinstance(dimension, ReviewDimension):
        return dimension.id
    return dimension


def _stable_id(prefix: str, parts: list[Any]) -> str:
    """A deterministic short id derived from stable content, for reproducible reports."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"

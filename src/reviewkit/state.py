"""Mutable review state accumulated across hierarchy levels."""

from __future__ import annotations

from pydantic import BaseModel, Field

from reviewkit.models import ActionStatus, ReviewActionType, ReviewResponse, ReviewScope


class ReviewState(BaseModel):
    repeated_issues: list[str] = Field(default_factory=list)
    style_observations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    paragraph_summaries: dict[str, str] = Field(default_factory=dict)
    section_summaries: dict[str, str] = Field(default_factory=dict)
    human_decisions: list[str] = Field(default_factory=list)
    document_summary: str | None = None

    def absorb_response(
        self,
        scope: ReviewScope,
        node_id: str,
        response: ReviewResponse,
    ) -> None:
        _extend_unique(self.repeated_issues, response.repeated_issues)
        _extend_unique(self.style_observations, response.style_observations)
        _extend_unique(self.risks, response.risks)
        _extend_unique(self.questions, response.questions)
        _extend_unique(self.missing_elements, response.missing_elements)
        _extend_unique(self.human_decisions, response.human_decisions)

        if response.summary:
            if scope == ReviewScope.PARAGRAPH:
                self.paragraph_summaries[node_id] = response.summary
            elif scope == ReviewScope.SECTION:
                self.section_summaries[node_id] = response.summary
            elif scope == ReviewScope.DOCUMENT:
                self.document_summary = response.summary

        for action in response.actions:
            detail = action.comment or action.reason or action.original_text
            if not detail:
                continue
            if action.action_type == ReviewActionType.RISK:
                _append_unique(self.risks, detail)
            elif action.action_type == ReviewActionType.QUESTION:
                _append_unique(self.questions, detail)
            if action.status == ActionStatus.NEEDS_HUMAN_DECISION:
                _append_unique(self.human_decisions, detail)


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        _append_unique(target, value)


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)

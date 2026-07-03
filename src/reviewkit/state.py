"""Mutable review state accumulated across hierarchy levels."""

from __future__ import annotations

from pydantic import BaseModel, Field

from reviewkit.models import (
    ActionStatus,
    ReviewActionType,
    ReviewFinding,
    ReviewResponse,
    ReviewScope,
)


class ReviewState(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
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
        self._add_findings(response.findings)

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

    def _add_findings(self, findings: list[ReviewFinding]) -> None:
        """Accumulate findings, skipping ones already seen.

        The same finding is often re-surfaced when a higher level echoes a lower
        level's observation. ``state.findings`` is the single source of truth for
        both prompt context and the final report, so deduplicate here to avoid
        inflating prompts and double-counting in the result. A finding is a
        duplicate if it shares an explicit ``finding_id`` (the stable key a caller
        reuses to re-surface the same finding) or if its full content matches.
        """
        seen_ids = {finding.finding_id for finding in self.findings}
        seen_content = {_finding_content_key(finding) for finding in self.findings}
        for finding in findings:
            content_key = _finding_content_key(finding)
            if finding.finding_id in seen_ids or content_key in seen_content:
                continue
            seen_ids.add(finding.finding_id)
            seen_content.add(content_key)
            self.findings.append(finding)


def _finding_content_key(finding: ReviewFinding) -> tuple[str, str, str, str, str]:
    return (
        finding.node_id,
        finding.title,
        finding.description,
        str(finding.dimension),
        finding.severity,
    )


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        _append_unique(target, value)


def _append_unique(target: list[str], value: str) -> None:
    if value and value not in target:
        target.append(value)

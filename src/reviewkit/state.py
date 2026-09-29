"""Mutable review state accumulated across hierarchy levels."""

from __future__ import annotations

from pydantic import BaseModel, Field

from reviewkit.models import ReviewFinding
from reviewkit.pack import FunctionTag


class ReviewState(BaseModel):
    findings: list[ReviewFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repeated_issues: list[str] = Field(default_factory=list)
    style_observations: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    paragraph_summaries: dict[str, str] = Field(default_factory=dict)
    section_summaries: dict[str, str] = Field(default_factory=dict)
    human_decisions: list[str] = Field(default_factory=list)
    document_summary: str | None = None
    tags: list[FunctionTag] = Field(default_factory=list)

    def covered(self) -> dict[str, list[str]]:
        """Function id to the node ids named with it. The host computes gaps from this."""
        found: dict[str, list[str]] = {}
        for tag in self.tags:
            for function_id in tag.function_ids:
                nodes = found.setdefault(function_id, [])
                if tag.node_id not in nodes:
                    nodes.append(tag.node_id)
        return found

    def functions_for(self, node_id: str) -> list[str]:
        for tag in self.tags:
            if tag.node_id == node_id:
                return list(tag.function_ids)
        return []

    def _add_findings(self, findings: list[ReviewFinding]) -> None:
        """Accumulate findings, merging re-surfacings of the same finding.

        The same finding is often re-surfaced when a higher level echoes a lower
        level's observation, and hierarchical review is designed so higher levels
        *enrich* lower-level ones (adding evidence or rationale, raising
        confidence). ``state.findings`` is the single source of truth for both
        prompt context and the final report, so collapse re-surfacings here to
        avoid inflating prompts and double-counting. Two findings are the same
        when they share a ``finding_id`` or when their core content matches
        (``node_id``/``title``/``description``/``dimension``/``severity``). On a
        match the surviving finding keeps the *richer* content of the two, so
        later enrichment is preserved rather than the earlier bare copy winning;
        a distinct ``finding_id`` from the merged-away copy is recorded under
        ``metadata["merged_finding_ids"]`` so an action still resolves to it.
        """
        by_id: dict[str, ReviewFinding] = {}
        by_content: dict[tuple[str, str, str, str, str], ReviewFinding] = {}
        for existing in self.findings:
            by_id[existing.finding_id] = existing
            by_content[_finding_content_key(existing)] = existing

        for finding in findings:
            content_key = _finding_content_key(finding)
            match = by_id.get(finding.finding_id) or by_content.get(content_key)
            if match is not None:
                _merge_finding(match, finding)
                by_id.setdefault(finding.finding_id, match)
                continue
            self.findings.append(finding)
            by_id[finding.finding_id] = finding
            by_content[content_key] = finding


def _merge_finding(existing: ReviewFinding, incoming: ReviewFinding) -> None:
    """Fold ``incoming`` into ``existing`` in place, keeping the richer content.

    The core identity/content fields are left as-is (they matched, or the
    ``finding_id`` matched); only the enrichable fields are combined so a later,
    richer re-surfacing is not discarded in favour of the earlier bare copy.
    """
    existing.confidence = max(existing.confidence, incoming.confidence)
    for item in incoming.evidence:
        if item not in existing.evidence:
            existing.evidence.append(item)
    known_events = {event.event_id for event in existing.lineage}
    existing.lineage += tuple(
        event for event in incoming.lineage if event.event_id not in known_events
    )
    if not existing.rationale and incoming.rationale:
        existing.rationale = incoming.rationale
    for key, value in incoming.metadata.items():
        existing.metadata.setdefault(key, value)
    if incoming.finding_id and incoming.finding_id != existing.finding_id:
        aliases = existing.metadata.setdefault("merged_finding_ids", [])
        if incoming.finding_id not in aliases:
            aliases.append(incoming.finding_id)


def _finding_content_key(finding: ReviewFinding) -> tuple[str, str, str, str, str]:
    return (
        finding.node_id,
        finding.title,
        finding.description,
        str(finding.dimension),
        finding.severity,
    )

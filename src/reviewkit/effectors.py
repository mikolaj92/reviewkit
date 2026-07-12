"""Effector adapters for takt 0.1.2 in ReviewKit.

When a CascadeRegulator emits Actuation or SafetyInterlock for a node,
these adapters turn that decision + the rich LLM response (stored during detection)
into ReviewAction objects with correct status, and feed findings into ReviewState.

This preserves the existing rich ReviewAction model (locators, original_text,
replacement, comments, etc.) while the control flow (when to act, when to
escalate, entropy reduction) is driven by takt + splot + homeostat.
"""

from __future__ import annotations

from typing import Any

from takt import Actuation, OutgoingSignals, SafetyInterlock

from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewFinding,
    ReviewScope,
)
from reviewkit.state import ReviewState


class ReviewEffector:
    """Collects decisions from takt tacts and materializes ReviewActions + findings."""

    def __init__(self, state: ReviewState) -> None:
        self.state = state
        # node_id -> full LLM response (contains .findings and .actions)
        self._responses: dict[str, Any] = {}
        # node_id -> scope
        self._scopes: dict[str, ReviewScope] = {}
        self.actions: list[ReviewAction] = []
        self.findings: list[ReviewFinding] = []

    def register_response(
        self, node_id: str, scope: ReviewScope, response: Any
    ) -> None:
        """Called by detectors after they get an LLM response for a node."""
        self._responses[node_id] = response
        self._scopes[node_id] = scope

        # Immediately absorb findings into state (like old code did)
        if hasattr(response, "findings"):
            self.state._add_findings(response.findings)  # type: ignore[attr-defined]
            self.findings.extend(response.findings)
        # Replicate old absorb_response side effects for summaries etc.
        if hasattr(response, "summary") and response.summary:
            if scope == ReviewScope.DOCUMENT:
                self.state.document_summary = response.summary
            elif scope == ReviewScope.PARAGRAPH:
                self.state.paragraph_summaries[node_id] = response.summary
            elif scope == ReviewScope.SECTION:
                self.state.section_summaries[node_id] = response.summary
        if hasattr(response, "risks"):
            _extend_unique(self.state.risks, response.risks)
        if hasattr(response, "questions"):
            _extend_unique(self.state.questions, response.questions)
        if hasattr(response, "repeated_issues"):
            _extend_unique(self.state.repeated_issues, response.repeated_issues)
        if hasattr(response, "missing_elements"):
            _extend_unique(self.state.missing_elements, response.missing_elements)

    def apply_takt_decision(
        self, node_id: str, signals: OutgoingSignals
    ) -> list[ReviewAction]:
        """Turn one takt decision into zero or more ReviewActions with status."""
        if node_id not in self._responses:
            return []

        response = self._responses[node_id]
        candidate_actions: list[ReviewAction] = getattr(response, "actions", []) or []
        produced: list[ReviewAction] = []

        if signals.interlock:
            for ca in candidate_actions:
                status = (
                    ActionStatus.NEEDS_HUMAN_DECISION
                    if getattr(ca, "requires_human_decision", False)
                    else ActionStatus.CONFLICT
                )
                produced.append(
                    ca.model_copy(
                        update={
                            "status": status,
                            "policy_reason": signals.interlock.reason or "takt interlock",
                        }
                    )
                )
        elif signals.actuation:
            for ca in candidate_actions:
                produced.append(
                    ca.model_copy(
                        update={
                            "status": ActionStatus.APPLIED,
                            "policy_reason": "takt actuation",
                        }
                    )
                )
        else:
            for ca in candidate_actions:
                produced.append(
                    ca.model_copy(
                        update={
                            "status": ActionStatus.NOT_APPLIED,
                            "policy_reason": "within homeostat tolerance",
                        }
                    )
                )

        self.actions.extend(produced)
        return produced


__all__ = ["ReviewEffector"]
def _extend_unique(target: list[str], values: list[str]) -> None:
    for v in values or []:
        if v and v not in target:
            target.append(v)

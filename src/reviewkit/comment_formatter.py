"""Shared internal formatter for rendered review-action comments."""

from __future__ import annotations

from reviewkit.models import ReviewAction, ReviewActionType


def action_comment_label(action: ReviewAction) -> str:
    if action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.DELETE_TEXT,
        ReviewActionType.INSERT_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.DELETE,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }:
        if action.status.value == "applied":
            return "CORRECTION"
        if action.status.value == "conflict":
            return "CONFLICT"
        if action.status.value == "needs_human_decision":
            return "HUMAN_DECISION"
        return "SUGGESTION"
    if action.action_type == ReviewActionType.QUESTION:
        return "QUESTION"
    if action.action_type == ReviewActionType.RISK:
        return "RISK"
    if action.action_type == ReviewActionType.SUGGESTION:
        return "SUGGESTION"
    if action.action_type == ReviewActionType.PRAISE:
        return "PRAISE"
    if action.action_type == ReviewActionType.SUMMARY:
        return "SUMMARY"
    return "COMMENT"


def format_action_comment(action: ReviewAction) -> str:
    """Return the exact body ReviewKit writes for an action comment."""
    label = action_comment_label(action)
    parts = [f"{label}: {action.comment or action.reason or action.policy_reason or ''}".rstrip()]
    if action.original_text:
        parts.append(f"Original: {action.original_text!r}")
    if action.replacement_text:
        parts.append(f"Replacement: {action.replacement_text!r}")
    if action.category:
        parts.append(f"Category: {action.category}")
    if action.policy_reason:
        parts.append(f"Policy: {action.policy_reason}")
    if action.references:
        refs = ", ".join(reference.label or reference.source for reference in action.references)
        parts.append(f"References: {refs}")
    if action.evidence_refs:
        evidence = ", ".join(
            ref.locator or ref.segment_id or ref.source or "evidence"
            for ref in action.evidence_refs
        )
        parts.append(f"Evidence: {evidence}")
    parts.append(f"Status: {action.status.value}")
    return "\n".join(parts)

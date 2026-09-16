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
    """Return the reader-facing body ReviewKit writes for an action comment.

    ``ReviewAction`` also carries identifiers, policy state, locators, evidence,
    and references for audit and downstream reconciliation. Those machine fields
    are deliberately not serialized into a physical Word comment: callers must
    put any user-facing explanation or non-citation basis into
    ``comment``/``reason`` while the complete action remains available to the
    audit carrier. Explicit reference labels are the one structured citation
    projection retained for a reader; unlabeled sources and all evidence
    locators remain audit-only.
    """
    label = action_comment_label(action)
    parts = [f"{label}: {action.comment or action.reason or ''}".rstrip()]
    if action.original_text:
        parts.append(f"Original: {action.original_text!r}")
    if action.replacement_text:
        parts.append(f"Replacement: {action.replacement_text!r}")
    references = [
        reference.label.strip()
        for reference in action.references
        if reference.label and reference.label.strip()
    ]
    if references:
        parts.append(f"References: {', '.join(references)}")
    return "\n".join(parts)


def format_legacy_action_comment(action: ReviewAction) -> str:
    """Return the exact pre-0.23 physical comment projection.

    Historical reviewed DOCX artifacts can carry this body even when their
    persisted action evidence has since gained lineage. Keep the old projection
    separate from the current reader-facing formatter so provenance can match a
    hash-bound historical artifact without changing newly rendered comments.
    """
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

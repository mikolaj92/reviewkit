"""Provider-blind finality assessment for a review action ledger."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import AbstractSet

from pydantic import BaseModel, ConfigDict, Field

from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType
from reviewkit.policy import WRITING_ACTIONS

POLICY_BLOCKED_FROM_CORRECTED = "blocked_from_corrected"


class ReviewFinalityStatus(StrEnum):
    """Whether every finding has a terminal review-action disposition."""

    FINAL = "final"
    NEEDS_REVIEW = "needs_review"


class ReviewFinalityAssessment(BaseModel):
    """Content-free counts and the conservative action-ledger decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ReviewFinalityStatus
    findings: int = Field(ge=0)
    suggested_actions: int = Field(ge=0)
    applied_edits: int = Field(ge=0)
    rejected_actions: int = Field(ge=0)
    unresolved_actions: int = Field(ge=0)
    reason: str | None = None


def assess_review_finality(
    *,
    finding_ids: Sequence[str],
    actions: Sequence[ReviewAction],
    suggested_categories: AbstractSet[str] = frozenset(),
    unresolved_categories: AbstractSet[str] = frozenset(),
) -> ReviewFinalityAssessment:
    """Assess whether all findings have conservative terminal dispositions.

    Finding identity is canonical only through ``ReviewAction.finding_id``. Callers
    inject category sets because category vocabulary belongs to the host domain.
    """
    expected_finding_ids = _normalise_finding_ids(finding_ids)
    suggested_action_count = sum(
        action.category in suggested_categories
        or action.action_type in {ReviewActionType.SUGGESTION, ReviewActionType.QUESTION}
        for action in actions
    )
    applied_actions = [action for action in actions if _is_applied_writing(action)]
    rejected_actions = [action for action in actions if _is_explicit_rejection(action)]
    unresolved_action_count = sum(
        _is_unresolved_action(action, unresolved_categories=unresolved_categories)
        for action in actions
    )

    applied_ids, unmapped_applied = _finding_ids_for(applied_actions)
    rejected_ids, unmapped_rejected = _finding_ids_for(rejected_actions)
    disposed_ids = applied_ids | rejected_ids
    unexpected_ids = disposed_ids - expected_finding_ids
    missing_ids = expected_finding_ids - disposed_ids

    if unresolved_action_count:
        status = ReviewFinalityStatus.NEEDS_REVIEW
        reason = "unresolved_review_actions"
    elif suggested_action_count:
        status = ReviewFinalityStatus.NEEDS_REVIEW
        reason = "suggested_actions_require_review"
    elif unmapped_applied:
        status = ReviewFinalityStatus.NEEDS_REVIEW
        reason = "applied_edits_without_finding_mapping"
    elif unmapped_rejected or missing_ids or unexpected_ids:
        status = ReviewFinalityStatus.NEEDS_REVIEW
        reason = "findings_without_applied_edits"
    else:
        status = ReviewFinalityStatus.FINAL
        reason = None

    return ReviewFinalityAssessment(
        status=status,
        findings=len(expected_finding_ids),
        suggested_actions=suggested_action_count,
        applied_edits=len(applied_actions),
        rejected_actions=len(rejected_actions),
        unresolved_actions=unresolved_action_count,
        reason=reason,
    )


def _normalise_finding_ids(finding_ids: Sequence[str]) -> frozenset[str]:
    normalised = tuple(str(value).strip() for value in finding_ids)
    if any(not value for value in normalised) or len(set(normalised)) != len(normalised):
        raise ValueError("finding_ids must contain unique non-empty strings")
    return frozenset(normalised)


def _finding_ids_for(actions: Sequence[ReviewAction]) -> tuple[frozenset[str], bool]:
    finding_ids = frozenset(action.finding_id for action in actions if action.finding_id)
    return finding_ids, any(not action.finding_id for action in actions)


def _is_applied_writing(action: ReviewAction) -> bool:
    return (
        action.status is ActionStatus.APPLIED
        and action.apply_to_corrected is True
        and action.action_type in WRITING_ACTIONS
    )


def _is_policy_blocked(action: ReviewAction) -> bool:
    return action.metadata.get(POLICY_BLOCKED_FROM_CORRECTED) is True


def _is_explicit_rejection(action: ReviewAction) -> bool:
    return (
        action.status is ActionStatus.NOT_APPLIED
        and action.action_type in WRITING_ACTIONS
        and action.apply_to_corrected is not True
        and not action.requires_human_decision
        and not _is_policy_blocked(action)
    )


def _is_unresolved_action(
    action: ReviewAction,
    *,
    unresolved_categories: AbstractSet[str],
) -> bool:
    if not (
        action.action_type in WRITING_ACTIONS or action.category in unresolved_categories
    ):
        return False
    if action.status in {ActionStatus.NEEDS_HUMAN_DECISION, ActionStatus.CONFLICT}:
        return True
    if action.requires_human_decision:
        return True
    if _is_policy_blocked(action) and action.status is ActionStatus.NOT_APPLIED:
        return True
    return (
        action.status is ActionStatus.NOT_APPLIED
        and action.apply_to_corrected is True
        and action.action_type in WRITING_ACTIONS
    )

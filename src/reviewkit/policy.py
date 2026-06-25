"""Action policy evaluation and safety guards."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType
from reviewkit.profile import ActionPolicyConfig, ReviewProfile

WRITING_ACTIONS = {
    ReviewActionType.REPLACE,
    ReviewActionType.DELETE,
    ReviewActionType.INSERT_BEFORE,
    ReviewActionType.INSERT_AFTER,
}

_SEVERITY_ORDER = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

@dataclass(frozen=True)
class ActionPolicyDecision:
    status: ActionStatus
    reason: str
    blocks_corrected: bool = False


class ActionPolicy:
    def __init__(self, config: ActionPolicyConfig) -> None:
        self.config = config

    @classmethod
    def from_profile(cls, profile: ReviewProfile) -> "ActionPolicy":
        return cls(profile.resolved_action_policy())

    def decide(self, action: ReviewAction, *, node_text: str) -> ActionPolicyDecision:
        policy_status = self._status_from_category_policy(action)
        if policy_status != ActionStatus.APPLIED:
            return ActionPolicyDecision(
                status=policy_status,
                reason=self._reason_for_status(policy_status, action),
            )

        if action.action_type not in WRITING_ACTIONS:
            return ActionPolicyDecision(
                status=ActionStatus.NOT_APPLIED,
                reason="Only writing actions can be applied automatically.",
            )

        if action.action_type not in self.config.allowed_action_types_for_auto_apply:
            return ActionPolicyDecision(
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                reason=f"Action type {action.action_type.value!r} is blocked by action policy.",
            )

        if action.category in self.config.blocked_categories:
            return ActionPolicyDecision(
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                reason=f"Category {action.category!r} is blocked by action policy.",
                blocks_corrected=True,
            )

        if action.requires_human_decision and self.config.block_when_requires_human_decision:
            return ActionPolicyDecision(
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                reason="Action requested human decision and policy blocks auto-apply.",
            )

        if self.config.require_llm_apply_hint and action.apply_to_corrected is not True:
            return ActionPolicyDecision(
                status=ActionStatus.NOT_APPLIED,
                reason="Policy requires explicit model apply_to_corrected=true.",
            )

        if action.confidence < self.config.min_confidence_for_auto_apply:
            return ActionPolicyDecision(
                status=ActionStatus.NOT_APPLIED,
                reason=(
                    "Action confidence is below policy threshold "
                    f"{self.config.min_confidence_for_auto_apply}."
                ),
            )

        if _severity_rank(action.severity) > _severity_rank(
            self.config.max_severity_for_auto_apply
        ):
            return ActionPolicyDecision(
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                reason=(
                    f"Action severity {action.severity!r} exceeds policy threshold "
                    f"{self.config.max_severity_for_auto_apply!r}."
                ),
            )

        if (
            action.priority is not None
            and self.config.max_priority_for_auto_apply is not None
            and _priority_rank(action.priority, self.config.priority_order)
            > _priority_rank(self.config.max_priority_for_auto_apply, self.config.priority_order)
        ):
            return ActionPolicyDecision(
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                reason=(
                    f"Action priority {action.priority!r} exceeds policy threshold "
                    f"{self.config.max_priority_for_auto_apply!r}."
                ),
            )

        guard_reason = self._guard_reason(action, node_text=node_text)
        if guard_reason:
            return ActionPolicyDecision(
                status=ActionStatus.NEEDS_HUMAN_DECISION,
                reason=guard_reason,
                blocks_corrected=True,
            )

        return ActionPolicyDecision(
            status=ActionStatus.APPLIED,
            reason="Action satisfies the active action policy.",
        )

    def _status_from_category_policy(self, action: ReviewAction) -> ActionStatus:
        policy_key = action.category or action.action_type.value
        policy = self.config.apply_policy.get(policy_key)

        if policy == "apply":
            return ActionStatus.APPLIED
        if policy == "human_decision":
            return ActionStatus.NEEDS_HUMAN_DECISION
        if policy in {"suggest", "comment"}:
            return ActionStatus.NOT_APPLIED

        if action.action_type in {ReviewActionType.RISK, ReviewActionType.QUESTION}:
            return ActionStatus.NEEDS_HUMAN_DECISION
        if action.action_type in {
            ReviewActionType.COMMENT,
            ReviewActionType.SUGGESTION,
            ReviewActionType.PRAISE,
            ReviewActionType.SUMMARY,
        }:
            return ActionStatus.NOT_APPLIED
        if action.action_type in WRITING_ACTIONS:
            return ActionStatus.NEEDS_HUMAN_DECISION
        return ActionStatus.NOT_APPLIED

    def _guard_reason(self, action: ReviewAction, *, node_text: str) -> str | None:
        if not self.config.protected_patterns:
            return None

        changed_text = _apply_action_to_text(node_text, action)
        for protected in self.config.protected_patterns:
            if not protected.preserve:
                continue
            pattern = re.compile(protected.pattern)
            before = pattern.findall(node_text)
            if not before:
                continue
            after = pattern.findall(changed_text)
            if before != after:
                return (
                    f"Protected pattern {protected.name!r} changed during auto-apply; "
                    "human decision is required."
                )
        return None

    @staticmethod
    def _reason_for_status(status: ActionStatus, action: ReviewAction) -> str:
        if status == ActionStatus.NEEDS_HUMAN_DECISION:
            return f"Action {action.action_type.value!r} requires human decision by policy."
        if status == ActionStatus.NOT_APPLIED:
            return f"Action {action.action_type.value!r} is advisory under policy."
        return "Action status was resolved by policy."


def _severity_rank(value: str) -> int:
    return _SEVERITY_ORDER.get(value.strip().lower(), _SEVERITY_ORDER["medium"])


def _priority_rank(value: str, priority_order: Mapping[str, int]) -> int:
    normalized_order = {label.strip().lower(): rank for label, rank in priority_order.items()}
    return normalized_order.get(value.strip().lower(), normalized_order.get("medium", 1))


def _apply_action_to_text(text: str, action: ReviewAction) -> str:
    original = action.original_text or ""
    replacement = action.replacement_text or ""

    if action.action_type == ReviewActionType.REPLACE and original:
        return text.replace(original, replacement, 1)
    if action.action_type == ReviewActionType.DELETE and original:
        return text.replace(original, "", 1)
    if action.action_type == ReviewActionType.INSERT_BEFORE:
        if original:
            return text.replace(original, f"{replacement}{original}", 1)
        return f"{replacement}{text}"
    if action.action_type == ReviewActionType.INSERT_AFTER:
        if original:
            return text.replace(original, f"{original}{replacement}", 1)
        return f"{text}{replacement}"
    return text

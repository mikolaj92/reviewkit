"""Validation and deterministic application of review actions."""

from __future__ import annotations

from collections.abc import Iterable

from reviewkit.document import ParagraphNode, ReviewDocument
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile

WRITING_ACTIONS = {
    ReviewActionType.REPLACE,
    ReviewActionType.DELETE,
    ReviewActionType.INSERT_BEFORE,
    ReviewActionType.INSERT_AFTER,
}

COMMENT_ACTIONS = {
    ReviewActionType.COMMENT,
    ReviewActionType.QUESTION,
    ReviewActionType.RISK,
    ReviewActionType.SUGGESTION,
    ReviewActionType.PRAISE,
    ReviewActionType.SUMMARY,
}


def prepare_actions(
    document: ReviewDocument,
    profile: ReviewProfile,
    actions: Iterable[ReviewAction],
) -> list[ReviewAction]:
    policy = ActionPolicy.from_profile(profile)
    return [_prepare_action(document, policy, action) for action in actions]


def apply_actions_to_text(text: str, actions: Iterable[ReviewAction]) -> str:
    result = text
    for action in actions:
        if action.status != ActionStatus.APPLIED:
            continue
        result = apply_action_to_text(result, action)
    return result


def apply_corrections_to_text(text: str, actions: Iterable[ReviewAction]) -> str:
    result = text
    for action in actions:
        if not should_apply_to_corrected(action):
            continue
        result = apply_action_to_text(result, action)
    return result


def should_apply_to_corrected(action: ReviewAction) -> bool:
    if action.status == ActionStatus.CONFLICT:
        return False
    if action.metadata.get("blocked_from_corrected") is True:
        return False
    return action.action_type in WRITING_ACTIONS


def apply_action_to_text(text: str, action: ReviewAction) -> str:
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


def actions_for_paragraph(
    document: ReviewDocument,
    paragraph: ParagraphNode,
    actions: Iterable[ReviewAction],
) -> list[ReviewAction]:
    sentence_ids = document.sentence_ids_for_paragraph(paragraph)
    section_or_document_ids = {paragraph.section_id, document.id}
    selected: list[ReviewAction] = []

    for action in actions:
        if action.node_id == paragraph.id or action.node_id in sentence_ids:
            selected.append(action)
            continue
        if action.node_id in section_or_document_ids and action.original_text:
            if paragraph.text.count(action.original_text) == 1:
                selected.append(action)
    return selected


def _prepare_action(
    document: ReviewDocument,
    policy: ActionPolicy,
    action: ReviewAction,
) -> ReviewAction:
    conflict = _conflict_reason(document, action)
    if conflict:
        return action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, conflict),
                "policy_reason": conflict,
            }
        )

    node_text = document.get_node_text(action.node_id)
    if node_text is None:
        return action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(
                    action.reason, f"node_id does not exist: {action.node_id}"
                ),
                "policy_reason": f"node_id does not exist: {action.node_id}",
            }
        )
    decision = policy.decide(action, node_text=node_text)
    metadata = dict(action.metadata)
    if decision.blocks_corrected:
        metadata["blocked_from_corrected"] = True
    return action.model_copy(
        update={
            "status": decision.status,
            "policy_reason": decision.reason,
            "metadata": metadata,
        }
    )


def _conflict_reason(document: ReviewDocument, action: ReviewAction) -> str | None:
    node_text = document.get_node_text(action.node_id)
    if node_text is None:
        return f"node_id does not exist: {action.node_id}"

    if action.action_type in {ReviewActionType.REPLACE, ReviewActionType.DELETE}:
        if not action.original_text:
            return "original_text is required for replace/delete actions"

    if action.action_type in {
        ReviewActionType.REPLACE,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }:
        if action.action_type != ReviewActionType.INSERT_BEFORE and not action.replacement_text:
            return "replacement_text is required for this action"
        if action.action_type == ReviewActionType.INSERT_BEFORE and action.replacement_text is None:
            return "replacement_text is required for this action"

    if action.original_text:
        matches = node_text.count(action.original_text)
        if matches != 1:
            return (
                "original_text must match exactly once in node "
                f"{action.node_id}; found {matches} matches"
            )

    return None


def _append_reason(existing: str | None, addition: str) -> str:
    if existing:
        return f"{existing}; {addition}"
    return addition

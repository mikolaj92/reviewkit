"""Validation and deterministic application of review actions."""

from __future__ import annotations

from collections.abc import Iterable

from reviewkit.action_demote import demote_cross_scope_overlaps
from reviewkit.action_prepare import prepare_actions
from reviewkit.action_target import actions_for_paragraph
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType
from reviewkit.policy import WRITING_ACTIONS

__all__ = [
    "actions_for_paragraph",
    "apply_action_to_text",
    "apply_corrections_to_text",
    "demote_cross_scope_overlaps",
    "prepare_actions",
    "should_apply_to_corrected",
]


def apply_corrections_to_text(text: str, actions: Iterable[ReviewAction]) -> str:
    result = text
    applicable = [action for action in actions if should_apply_to_corrected(action)]
    for action in _actions_in_text_application_order(applicable):
        result = apply_action_to_text(result, action)
    return result


def should_apply_to_corrected(action: ReviewAction) -> bool:
    if action.status != ActionStatus.APPLIED:
        return False
    if action.metadata.get("blocked_from_corrected") is True:
        return False
    return action.action_type in WRITING_ACTIONS


def apply_action_to_text(text: str, action: ReviewAction) -> str:
    original = action.original_text or ""
    replacement = action.replacement_text or ""

    if (
        action.locator
        and action.locator.char_start is not None
        and action.locator.char_end is not None
    ):
        start = action.locator.char_start
        end = action.locator.char_end
        if action.action_type in {ReviewActionType.REPLACE_TEXT, ReviewActionType.REPLACE}:
            return f"{text[:start]}{replacement}{text[end:]}"
        if action.action_type in {ReviewActionType.DELETE_TEXT, ReviewActionType.DELETE}:
            return f"{text[:start]}{text[end:]}"
        if action.action_type in {ReviewActionType.INSERT_TEXT, ReviewActionType.INSERT_BEFORE}:
            return f"{text[:start]}{replacement}{text[start:]}"
        if action.action_type == ReviewActionType.INSERT_AFTER:
            return f"{text[:end]}{replacement}{text[end:]}"

    if action.action_type == ReviewActionType.REPLACE_TEXT and original:
        return text.replace(original, replacement, 1)
    if action.action_type == ReviewActionType.DELETE_TEXT and original:
        return text.replace(original, "", 1)
    if action.action_type == ReviewActionType.INSERT_TEXT:
        if original:
            return text.replace(original, f"{original}{replacement}", 1)
        return f"{text}{replacement}"
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


_ZERO_WIDTH_INSERTS = {
    ReviewActionType.INSERT_TEXT,
    ReviewActionType.INSERT_BEFORE,
    ReviewActionType.INSERT_AFTER,
}


def _find_anchor_application_order(actions: list[ReviewAction]) -> list[ReviewAction]:
    """Order find-based (offset-less) actions so one edit cannot consume another's anchor.

    These actions re-find ``original_text`` in the already-edited text, so application
    order decides whether a later anchor still exists. Two rules keep prepare-approved
    combinations applicable: zero-width insertions go first (they consume no text, while
    a replace/delete applied earlier would consume THEIR anchor), and APPLIED edits go
    before non-APPLIED suggestions (an APPLIED edit must always land; a suggestion whose
    anchor was consumed has a documented degrade to a labelled comment). The sort is
    stable, so equal-priority actions keep their listed order.
    """
    return sorted(
        actions,
        key=lambda action: (
            action.action_type not in _ZERO_WIDTH_INSERTS,
            action.status != ActionStatus.APPLIED,
        ),
    )


def _actions_in_text_application_order(actions: list[ReviewAction]) -> list[ReviewAction]:
    locator_actions: list[tuple[int, int, int, ReviewAction]] = []
    other_actions: list[ReviewAction] = []
    for index, action in enumerate(actions):
        action_range = _locator_range(action)
        if action_range is None:
            other_actions.append(action)
            continue
        start, end = action_range
        locator_actions.append((start, end, index, action))
    locator_actions.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in locator_actions] + _find_anchor_application_order(other_actions)


def _locator_range(action: ReviewAction) -> tuple[int, int] | None:
    if not action.locator:
        return None
    if action.locator.char_start is None or action.locator.char_end is None:
        return None
    if action.action_type not in WRITING_ACTIONS:
        return None
    if action.action_type == ReviewActionType.INSERT_AFTER:
        # INSERT_AFTER is a zero-width insertion at char_end (see apply_action_to_text),
        # not an edit spanning [char_start, char_end]. Order the right-to-left sweep by
        # that effective position, else a length-changing edit before char_end leaves a
        # stale offset and the insertion lands in the wrong place.
        return action.locator.char_end, action.locator.char_end
    return action.locator.char_start, action.locator.char_end

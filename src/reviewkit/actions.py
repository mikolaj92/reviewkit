"""Validation and deterministic application of review actions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from reviewkit.document import ParagraphNode, ReviewDocument, SentenceNode
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType, ReviewLocator
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile

WRITING_ACTIONS = {
    ReviewActionType.REPLACE_TEXT,
    ReviewActionType.DELETE_TEXT,
    ReviewActionType.INSERT_TEXT,
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
    policy: ActionPolicy | None = None,
) -> list[ReviewAction]:
    resolved_policy = policy if policy is not None else ActionPolicy.from_profile(profile)
    prepared = [_prepare_action(document, resolved_policy, action) for action in actions]
    return _demote_overlapping_actions(document, prepared)


def apply_actions_to_text(text: str, actions: Iterable[ReviewAction]) -> str:
    result = text
    applicable = [action for action in actions if action.status == ActionStatus.APPLIED]
    for action in _actions_in_text_application_order(applicable):
        result = apply_action_to_text(result, action)
    return result


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

    if action.locator and action.locator.char_start is not None and action.locator.char_end is not None:
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
    return [item[3] for item in locator_actions] + other_actions


def _locator_range(action: ReviewAction) -> tuple[int, int] | None:
    if not action.locator:
        return None
    if action.locator.char_start is None or action.locator.char_end is None:
        return None
    if action.action_type not in WRITING_ACTIONS:
        return None
    return action.locator.char_start, action.locator.char_end


def actions_for_paragraph(
    document: ReviewDocument,
    paragraph: ParagraphNode,
    actions: Iterable[ReviewAction],
) -> list[ReviewAction]:
    sentences_by_id = {sentence.id: sentence for sentence in paragraph.sentences}
    section_or_document_ids = {paragraph.section_id, document.id}
    selected: list[ReviewAction] = []

    for action in actions:
        if action.node_id == paragraph.id:
            selected.append(action)
            continue
        sentence = sentences_by_id.get(action.node_id)
        if sentence is not None:
            selected.append(_rebase_sentence_action(paragraph, sentence, action))
            continue
        if action.node_id in section_or_document_ids and action.original_text:
            if _scope_comment_anchor_id(document, action) == paragraph.id:
                selected.append(_clear_locator_offsets(action))
    return selected


def _scope_paragraphs(
    document: ReviewDocument, action: ReviewAction
) -> list[ParagraphNode]:
    """Ordered paragraphs that a section/document-scoped action ranges over."""
    if action.node_id == document.id:
        return list(document.iter_paragraphs())
    for section in document.sections:
        if section.id == action.node_id:
            return list(section.paragraphs)
    return []


def _scope_comment_anchor_id(
    document: ReviewDocument, action: ReviewAction
) -> str | None:
    """Single paragraph a scoped comment attaches to.

    A section/document-scoped comment carrying ``original_text`` used to attach to
    every paragraph where the text matched once (duplicated) or vanish when it never
    matched uniquely (dropped). Instead pick one well-defined anchor: the first
    paragraph in scope whose text contains the quote; if none does, fall back to the
    scope's first paragraph so the comment is surfaced rather than silently dropped.

    CONFLICT actions are anchored too: the reviewed renderer only turns an APPLIED
    edit into a tracked change, so a scoped conflict lands as a CONFLICT-labelled
    comment. Returning None here previously dropped scope-level conflicts entirely,
    silencing the very ambiguity that most needs human attention.
    """
    paragraphs = _scope_paragraphs(document, action)
    if not paragraphs:
        return None
    quote = action.original_text or ""
    for paragraph in paragraphs:
        if quote and quote in paragraph.text:
            return paragraph.id
    return paragraphs[0].id


def _sentence_base_offset(paragraph: ParagraphNode, sentence: SentenceNode) -> int | None:
    """Offset of ``sentence`` inside ``paragraph.text`` (parser span, else unique match)."""
    if sentence.char_start is not None:
        return sentence.char_start
    if sentence.text and paragraph.text.count(sentence.text) == 1:
        return paragraph.text.find(sentence.text)
    return None


def _rebase_sentence_action(
    paragraph: ParagraphNode,
    sentence: SentenceNode,
    action: ReviewAction,
) -> ReviewAction:
    """Translate a sentence-scoped action into paragraph coordinates.

    Sentence prompts only show the sentence text, so returned char offsets and
    unique-match guarantees are sentence-relative. Both renderers apply actions
    against the whole paragraph, so the offsets must be rebased first, otherwise
    the wrong span is edited.
    """
    base = _sentence_base_offset(paragraph, sentence)
    locator = action.locator

    if base is not None and locator is not None and (
        locator.char_start is not None or locator.char_end is not None
    ):
        updates: dict[str, Any] = {"node_id": paragraph.id}
        if locator.char_start is not None:
            updates["char_start"] = base + locator.char_start
        if locator.char_end is not None:
            updates["char_end"] = base + locator.char_end
        return action.model_copy(update={"locator": locator.model_copy(update=updates)})

    if base is not None and action.original_text and sentence.text.count(action.original_text) == 1:
        start = base + sentence.text.find(action.original_text)
        end = start + len(action.original_text)
        rebased = (locator or ReviewLocator()).model_copy(
            update={"node_id": paragraph.id, "char_start": start, "char_end": end}
        )
        return action.model_copy(update={"locator": rebased})

    # Cannot rebase safely: drop sentence-relative offsets so application falls
    # back to whole-paragraph text matching rather than a wrong offset slice.
    return _clear_locator_offsets(action)


def _clear_locator_offsets(action: ReviewAction) -> ReviewAction:
    locator = action.locator
    if locator is None or (locator.char_start is None and locator.char_end is None):
        return action
    return action.model_copy(
        update={"locator": locator.model_copy(update={"char_start": None, "char_end": None})}
    )


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


def _demote_overlapping_actions(
    document: ReviewDocument, actions: list[ReviewAction]
) -> list[ReviewAction]:
    """Escalate APPLIED writing edits whose char ranges overlap on the same node.

    Each action is validated against the original node text in isolation, so two
    edits that individually pass can still target overlapping spans of one node.
    The text-application sweep would then overwrite one edit with the other,
    silently losing it. Overlapping edits are ambiguous, so demote every action
    in an overlapping cluster to CONFLICT rather than guessing which one wins.
    """
    ranges_by_node: dict[str, list[tuple[int, int, int]]] = {}
    for index, action in enumerate(actions):
        if action.status != ActionStatus.APPLIED or action.action_type not in WRITING_ACTIONS:
            continue
        node_text = document.get_node_text(action.node_id)
        if node_text is None:
            continue
        span = _applied_char_range(node_text, action)
        if span is None:
            continue
        ranges_by_node.setdefault(action.node_id, []).append((span[0], span[1], index))

    overlapping: set[int] = set()
    for spans in ranges_by_node.values():
        spans.sort()
        cluster: list[int] = []
        cluster_end = 0
        for start, end, index in spans:
            if cluster and start < cluster_end:
                overlapping.update(cluster)
                overlapping.add(index)
                cluster.append(index)
                cluster_end = max(cluster_end, end)
            else:
                cluster = [index]
                cluster_end = end
    if not overlapping:
        return actions

    reason = "overlapping edit range conflicts with another edit on the same node"
    result = list(actions)
    for index in overlapping:
        action = result[index]
        result[index] = action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, reason),
                "policy_reason": reason,
            }
        )
    return result


def _applied_char_range(node_text: str, action: ReviewAction) -> tuple[int, int] | None:
    """Span of ``node_text`` an APPLIED writing action mutates, if determinable."""
    locator = action.locator
    if locator and locator.char_start is not None and locator.char_end is not None:
        return locator.char_start, locator.char_end
    original = action.original_text
    if original and node_text.count(original) == 1:
        start = node_text.find(original)
        return start, start + len(original)
    return None


def _conflict_reason(document: ReviewDocument, action: ReviewAction) -> str | None:
    node_text = document.get_node_text(action.node_id)
    if node_text is None:
        return f"node_id does not exist: {action.node_id}"

    locator_reason = _locator_conflict_reason(node_text, action)
    if locator_reason:
        return locator_reason

    if action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.DELETE_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.DELETE,
    }:
        if not action.original_text:
            return "original_text is required for replace/delete actions"

    if action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.INSERT_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }:
        if action.action_type not in {
            ReviewActionType.INSERT_TEXT,
            ReviewActionType.INSERT_BEFORE,
        } and not action.replacement_text:
            return "replacement_text is required for this action"
        if action.action_type in {
            ReviewActionType.INSERT_TEXT,
            ReviewActionType.INSERT_BEFORE,
        } and action.replacement_text is None:
            return "replacement_text is required for this action"

    if action.original_text:
        matches = node_text.count(action.original_text)
        if matches != 1:
            return (
                "original_text must match exactly once in node "
                f"{action.node_id}; found {matches} matches"
            )

    return None


def _locator_conflict_reason(node_text: str, action: ReviewAction) -> str | None:
    locator = action.locator
    if locator is None:
        return None
    if locator.node_id is not None and locator.node_id != action.node_id:
        return "locator node_id does not match action node_id"
    if locator.node_hash is not None and locator.node_hash != locator.hash_text(node_text):
        return "locator node_hash does not match current node text"
    if locator.char_start is None and locator.char_end is None:
        return None
    if locator.char_start is None or locator.char_end is None:
        return "locator char_start and char_end must be provided together"
    if locator.char_end < locator.char_start:
        return "locator char_end must be greater than or equal to char_start"
    if locator.char_end > len(node_text):
        return "locator range is outside the current node text"

    located_text = node_text[locator.char_start : locator.char_end]
    expected_text = locator.original_text or action.original_text
    if expected_text is not None and located_text != expected_text:
        return "locator text does not match current node text"
    if locator.text_hash is not None and locator.text_hash != locator.hash_text(located_text):
        return "locator text_hash does not match current node text"
    return None


def _append_reason(existing: str | None, addition: str) -> str:
    if existing:
        return f"{existing}; {addition}"
    return addition

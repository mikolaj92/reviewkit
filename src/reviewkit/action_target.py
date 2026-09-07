"""Resolve review actions onto the paragraph they edit."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from reviewkit.document import ParagraphNode, ReviewDocument, SentenceNode
from reviewkit.models import ReviewAction, ReviewLocator


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
        if (
            action.node_id in section_or_document_ids
            and _scope_anchor_id(document, action) == paragraph.id
        ):
            selected.append(_clear_locator_offsets(action))
    return selected


def scope_paragraphs(document: ReviewDocument, action: ReviewAction) -> list[ParagraphNode]:
    """Ordered paragraphs that a section/document-scoped action ranges over."""
    if action.node_id == document.id:
        return list(document.iter_paragraphs())
    for section in document.sections:
        if section.id == action.node_id:
            return list(section.paragraphs)
    return []


def _scope_anchor_id(document: ReviewDocument, action: ReviewAction) -> str | None:
    """Return the canonical paragraph anchor, or None when the quote cannot be anchored."""
    quote = action.original_text
    if not quote:
        return None
    for paragraph in scope_paragraphs(document, action):
        if quote in paragraph.text:
            return paragraph.id
    return None


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

    if (
        base is not None
        and locator is not None
        and (locator.char_start is not None or locator.char_end is not None)
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

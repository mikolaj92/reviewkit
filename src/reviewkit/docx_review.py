"""Review one DOCX by walking that same file.

The walk is the review. Side effects land on the file during the walk, not
only in a new output written after it finishes.

Order: every zdanie (stay-or-go), then every akapit, then every rozdział,
then całość n times.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from reviewkit.comments import comments_overlapping_span
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.docx_effects import apply_effect
from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewResult,
    ReviewScope,
    ReviewStats,
)
from reviewkit.parser_docx import load_docx
from reviewkit.poziom import WALK_ORDER, Poziom
from reviewkit.stay import StayOrGo, stay_loop
from reviewkit.visit import DocxReviewer, Effect, EffectKind, Unit, Visit

_POZIOM_SCOPE = {
    Poziom.ZDANIE: ReviewScope.SENTENCE,
    Poziom.AKAPIT: ReviewScope.PARAGRAPH,
    Poziom.ROZDZIAL: ReviewScope.SECTION,
    Poziom.CALOSC: ReviewScope.DOCUMENT,
}

_EFFECT_ACTION = {
    EffectKind.ADD_COMMENT: ReviewActionType.COMMENT,
    EffectKind.UPDATE_COMMENT: ReviewActionType.COMMENT,
    EffectKind.DELETE_COMMENT: ReviewActionType.COMMENT,
    EffectKind.CHANGE_TEXT: ReviewActionType.REPLACE_TEXT,
}


def review_docx(
    path: str | Path,
    reviewer: DocxReviewer,
    *,
    author: str = "Reviewer",
    initials: str = "RV",
    max_stays: int = 32,
) -> ReviewResult:
    """Walk one DOCX in place. ``path`` is the file the review mutates."""
    live = Path(path)
    if not live.is_file():
        raise FileNotFoundError(live)

    visits: list[dict[str, object]] = []
    actions: list[ReviewAction] = []

    for poziom in WALK_ORDER:
        keys = [unit.key for unit in _units(load_docx(live), poziom)]
        for key in keys:

            def step(
                visit_index: int, *, current_key: str = key, current: Poziom = poziom
            ) -> StayOrGo:
                unit = _unit_by_key(load_docx(live), current, current_key)
                decision = reviewer.visit(Visit(unit=unit, visit_index=visit_index, path=live))
                for effect in decision.effects:
                    apply_effect(live, unit, effect, author=author, initials=initials)
                    actions.append(_action_from_effect(unit, effect, len(actions)))
                visits.append(
                    {
                        "poziom": current.value,
                        "key": current_key,
                        "node_id": unit.node_id,
                        "visit_index": visit_index,
                    }
                )
                return decision.stay_or_go

            stay_loop(step, max_stays=max_stays, node_id=key)

    document = load_docx(live)
    return ReviewResult(
        document=document,
        actions=actions,
        reviewed_docx=live,
        stats=ReviewStats.from_actions(actions),
        artifacts={"reviewed_docx": str(live)},
        metrics={"walk": visits},
    )


def _units(document: ReviewDocument, poziom: Poziom) -> list[Unit]:
    if poziom is Poziom.ZDANIE:
        return [
            _zdanie(sentence, paragraph, document)
            for paragraph in _akapity(document)
            for sentence in paragraph.sentences
        ]
    if poziom is Poziom.AKAPIT:
        return [_akapit(paragraph, document) for paragraph in _akapity(document)]
    if poziom is Poziom.ROZDZIAL:
        return [_rozdzial(section, document) for section in _rozdzialy(document)]
    return [_calosc(document)]


def _unit_by_key(document: ReviewDocument, poziom: Poziom, key: str) -> Unit:
    for unit in _units(document, poziom):
        if unit.key == key:
            return unit
    raise LookupError(f"{poziom.value} {key!r} is gone from the live DOCX")


def _akapity(document: ReviewDocument) -> Iterator[ParagraphNode]:
    for section in _rozdzialy(document):
        yield from section.paragraphs


def _rozdzialy(document: ReviewDocument) -> Iterator[SectionNode]:
    for section in document.sections:
        if section.metadata.get("source") in {"header", "footer"}:
            continue
        yield section


def _zdanie(sentence: SentenceNode, paragraph: ParagraphNode, document: ReviewDocument) -> Unit:
    comments = comments_overlapping_span(
        document.comments,
        paragraph.locator,
        sentence.char_start,
        sentence.char_end,
    )
    return Unit(
        poziom=Poziom.ZDANIE,
        key=sentence.locator or sentence.id,
        node_id=sentence.id,
        text=paragraph.text,
        locator=paragraph.locator,
        char_start=sentence.char_start,
        char_end=sentence.char_end,
        comments=tuple(comments),
    )


def _akapit(paragraph: ParagraphNode, document: ReviewDocument) -> Unit:
    comments = comments_overlapping_span(
        document.comments, paragraph.locator, 0, len(paragraph.text)
    )
    return Unit(
        poziom=Poziom.AKAPIT,
        key=paragraph.locator or paragraph.id,
        node_id=paragraph.id,
        text=paragraph.text,
        locator=paragraph.locator,
        char_start=0,
        char_end=len(paragraph.text),
        comments=tuple(comments),
    )


def _rozdzial(section: SectionNode, document: ReviewDocument) -> Unit:
    paragraph = next(iter(section.paragraphs), None)
    locator = (paragraph.locator if paragraph is not None else None) or section.locator
    text = section.text
    comments = tuple(
        comment
        for paragraph in section.paragraphs
        for comment in comments_overlapping_span(
            document.comments, paragraph.locator, 0, len(paragraph.text)
        )
    )
    return Unit(
        poziom=Poziom.ROZDZIAL,
        key=section.id,
        node_id=section.id,
        text=text,
        locator=locator,
        char_start=0 if paragraph is not None else None,
        char_end=len(paragraph.text) if paragraph is not None else None,
        comments=comments,
    )


def _calosc(document: ReviewDocument) -> Unit:
    paragraph = next(_akapity(document), None)
    return Unit(
        poziom=Poziom.CALOSC,
        key=Poziom.CALOSC.value,
        node_id=document.id,
        text=document.text,
        locator=paragraph.locator if paragraph is not None else None,
        char_start=0 if paragraph is not None else None,
        char_end=len(paragraph.text) if paragraph is not None else None,
        comments=tuple(document.comments),
    )


def _action_from_effect(unit: Unit, effect: Effect, index: int) -> ReviewAction:
    return ReviewAction(
        id=f"walk-{index}-{effect.kind.value}",
        scope=_POZIOM_SCOPE[unit.poziom],
        action_type=_EFFECT_ACTION[effect.kind],
        node_id=unit.node_id,
        original_text=effect.original_text,
        replacement_text=effect.replacement_text,
        comment=effect.comment,
        status=ActionStatus.APPLIED,
        metadata={"effect": effect.kind.value, "comment_id": effect.comment_id or ""},
    )


__all__ = ["review_docx"]

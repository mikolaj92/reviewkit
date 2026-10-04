"""Stay-or-go walk over one live DOCX: zdanie, then akapit, then rozdział, then całość."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from reviewkit.comments import DocxComment, comments_for_locator
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.levels import AKAPIT, CALOSC, LEVEL_ORDER, ROZDZIAL, ZDANIE
from reviewkit.live_docx import LiveDocx, LiveDocxError


class StayOrGo(StrEnum):
    STAY = "stay"
    GO = "go"


@dataclass(frozen=True)
class ReviewUnit:
    """One unit of the live file at the current walk level."""

    level: str
    node_id: str
    text: str
    locator: str | None
    paragraph_locator: str | None
    paragraph_locators: tuple[str, ...]
    char_start: int | None
    char_end: int | None
    comments: tuple[DocxComment, ...]
    stay_index: int = 0
    calosc_pass: int | None = None

    def at_stay(self, stay_index: int, *, calosc_pass: int | None = None) -> ReviewUnit:
        return ReviewUnit(
            level=self.level,
            node_id=self.node_id,
            text=self.text,
            locator=self.locator,
            paragraph_locator=self.paragraph_locator,
            paragraph_locators=self.paragraph_locators,
            char_start=self.char_start,
            char_end=self.char_end,
            comments=self.comments,
            stay_index=stay_index,
            calosc_pass=self.calosc_pass if calosc_pass is None else calosc_pass,
        )


@dataclass(frozen=True)
class WalkVisit:
    level: str
    node_id: str
    stay_index: int
    calosc_pass: int | None
    text: str


class WalkLimitError(RuntimeError):
    """Stay-or-go stayed on one unit past the allowed bound."""


_STORY_SKIP = frozenset({"header", "footer", "comment", "footnote", "endnote"})


def list_units(document: ReviewDocument, level: str) -> tuple[ReviewUnit, ...]:
    comments = tuple(document.comments)
    if level == ZDANIE:
        return tuple(
            _sentence_unit(sentence, paragraph, comments)
            for paragraph in _body_paragraphs(document)
            for sentence in paragraph.sentences
        )
    if level == AKAPIT:
        return tuple(
            _paragraph_unit(paragraph, comments) for paragraph in _body_paragraphs(document)
        )
    if level == ROZDZIAL:
        return tuple(
            _chapter_unit(section, comments)
            for section in document.sections
            if _body_section(section)
        )
    if level == CALOSC:
        return (_document_unit(document, comments),)
    raise ValueError(f"unknown walk level: {level!r}")


DecideFn = Callable[[ReviewUnit, LiveDocx], StayOrGo]


def walk_live_docx(
    live: LiveDocx,
    decide: DecideFn,
    *,
    calosc_times: int = 1,
    max_stays: int = 64,
) -> tuple[WalkVisit, ...]:
    """Walk the live file. ``decide`` is ``decide(unit, live) -> StayOrGo``."""
    if calosc_times < 1:
        raise ValueError("calosc_times must be at least 1")
    if max_stays < 1:
        raise ValueError("max_stays must be at least 1")
    visits: list[WalkVisit] = []
    for level in LEVEL_ORDER:
        if level == CALOSC:
            for calosc_pass in range(calosc_times):
                units = list_units(live.load(), CALOSC)
                _stay_or_go(live, decide, units[0], visits, max_stays, calosc_pass)
            continue
        for unit in list_units(live.load(), level):
            _stay_or_go(live, decide, unit, visits, max_stays, None)
    return tuple(visits)


def _stay_or_go(
    live: LiveDocx,
    decide: DecideFn,
    seed: ReviewUnit,
    visits: list[WalkVisit],
    max_stays: int,
    calosc_pass: int | None,
) -> None:
    stay_index = 0
    while True:
        unit = _refresh(live, seed).at_stay(stay_index, calosc_pass=calosc_pass)
        visits.append(
            WalkVisit(
                level=unit.level,
                node_id=unit.node_id,
                stay_index=unit.stay_index,
                calosc_pass=unit.calosc_pass,
                text=unit.text,
            )
        )
        decision = decide(unit, live)
        if decision is StayOrGo.GO:
            return
        if decision is not StayOrGo.STAY:
            raise TypeError(f"decide must return StayOrGo, got {decision!r}")
        stay_index += 1
        if stay_index > max_stays:
            raise WalkLimitError(
                f"stayed on {unit.level} {unit.node_id!r} more than {max_stays} times"
            )


def _refresh(live: LiveDocx, seed: ReviewUnit) -> ReviewUnit:
    document = live.load()
    for unit in list_units(document, seed.level):
        if unit.node_id == seed.node_id:
            return unit
    raise LiveDocxError(f"unit {seed.node_id!r} at {seed.level} is gone from {live.path}")


def _body_paragraphs(document: ReviewDocument) -> tuple[ParagraphNode, ...]:
    return tuple(
        paragraph
        for paragraph in document.iter_paragraphs()
        if paragraph.metadata.get("source") not in _STORY_SKIP
    )


def _body_section(section: SectionNode) -> bool:
    source = section.metadata.get("source")
    if source in _STORY_SKIP:
        return False
    paragraphs = section.paragraphs
    skipped = all(paragraph.metadata.get("source") in _STORY_SKIP for paragraph in paragraphs)
    return not (paragraphs and skipped)


def _sentence_unit(
    sentence: SentenceNode, paragraph: ParagraphNode, comments: Sequence[DocxComment]
) -> ReviewUnit:
    locator = paragraph.locator
    return ReviewUnit(
        level=ZDANIE,
        node_id=sentence.id,
        text=sentence.text,
        locator=sentence.locator,
        paragraph_locator=locator,
        paragraph_locators=(locator,) if locator else (),
        char_start=sentence.char_start,
        char_end=sentence.char_end,
        comments=_comments_on_span(comments, locator, sentence.char_start, sentence.char_end),
    )


def _paragraph_unit(paragraph: ParagraphNode, comments: Sequence[DocxComment]) -> ReviewUnit:
    locator = paragraph.locator
    return ReviewUnit(
        level=AKAPIT,
        node_id=paragraph.id,
        text=paragraph.text,
        locator=locator,
        paragraph_locator=locator,
        paragraph_locators=(locator,) if locator else (),
        char_start=0,
        char_end=len(paragraph.text),
        comments=tuple(comments_for_locator(list(comments), locator)),
    )


def _chapter_unit(section: SectionNode, comments: Sequence[DocxComment]) -> ReviewUnit:
    locators = tuple(
        paragraph.locator for paragraph in section.paragraphs if paragraph.locator is not None
    )
    first = locators[0] if locators else section.locator
    return ReviewUnit(
        level=ROZDZIAL,
        node_id=section.id,
        text=section.text,
        locator=section.locator or first,
        paragraph_locator=first,
        paragraph_locators=locators,
        char_start=None,
        char_end=None,
        comments=tuple(
            comment
            for comment in comments
            if comment.locator is not None and comment.locator in locators
        ),
    )


def _document_unit(document: ReviewDocument, comments: Sequence[DocxComment]) -> ReviewUnit:
    locators = tuple(
        paragraph.locator
        for paragraph in _body_paragraphs(document)
        if paragraph.locator is not None
    )
    first = locators[0] if locators else None
    return ReviewUnit(
        level=CALOSC,
        node_id=document.id,
        text=document.text,
        locator=first,
        paragraph_locator=first,
        paragraph_locators=locators,
        char_start=None,
        char_end=None,
        comments=tuple(comments),
    )


def _comments_on_span(
    comments: Sequence[DocxComment],
    locator: str | None,
    start: int | None,
    end: int | None,
) -> tuple[DocxComment, ...]:
    matched = comments_for_locator(list(comments), locator)
    if start is None or end is None:
        return tuple(matched)
    sitting: list[DocxComment] = []
    for comment in matched:
        if comment.start_offset is None or comment.end_offset is None:
            sitting.append(comment)
            continue
        if comment.start_offset < end and comment.end_offset > start:
            sitting.append(comment)
    return tuple(sitting)


__all__ = [
    "DecideFn",
    "ReviewUnit",
    "StayOrGo",
    "WalkLimitError",
    "WalkVisit",
    "list_units",
    "walk_live_docx",
]

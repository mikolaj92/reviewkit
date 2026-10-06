"""Stay-or-go walk over one live DOCX: zdanie, then akapit, then rozdział, then całość."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from docxtor import PhysicalCommentSpan, ReviewCoverage, ReviewDiagnostic

from reviewkit.comments import DocxComment, comments_for_locator
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.levels import AKAPIT, CALOSC, ROZDZIAL, ZDANIE
from reviewkit.live_docx import LiveDocx


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
    physical_spans: tuple[PhysicalCommentSpan, ...] = ()
    document_sha256: str | None = None
    geometry_coverage: ReviewCoverage = ReviewCoverage.INCOMPLETE
    geometry_diagnostics: tuple[ReviewDiagnostic, ...] = ()

    def at_stay(self, stay_index: int) -> ReviewUnit:
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
            physical_spans=self.physical_spans,
            document_sha256=self.document_sha256,
            geometry_coverage=self.geometry_coverage,
            geometry_diagnostics=self.geometry_diagnostics,
        )


@dataclass(frozen=True)
class WalkVisit:
    level: str
    node_id: str
    stay_index: int
    text: str


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


def walk_live_docx(live: LiveDocx, decide: DecideFn) -> tuple[WalkVisit, ...]:
    """Walk the live file. ``decide`` is ``decide(unit, live) -> StayOrGo``."""
    visits: list[WalkVisit] = []
    _walk_zdania(live, decide, visits)
    _walk_akapity(live, decide, visits)
    _walk_rozdzialy(live, decide, visits)
    _walk_calosc(live, decide, visits)
    return tuple(visits)


def _walk_zdania(live: LiveDocx, decide: DecideFn, visits: list[WalkVisit]) -> None:
    _walk_level(live, decide, visits, ZDANIE)


def _walk_akapity(live: LiveDocx, decide: DecideFn, visits: list[WalkVisit]) -> None:
    _walk_level(live, decide, visits, AKAPIT)


def _walk_rozdzialy(live: LiveDocx, decide: DecideFn, visits: list[WalkVisit]) -> None:
    _walk_level(live, decide, visits, ROZDZIAL)


def _walk_calosc(live: LiveDocx, decide: DecideFn, visits: list[WalkVisit]) -> None:
    _walk_level(live, decide, visits, CALOSC)


def _walk_level(
    live: LiveDocx,
    decide: DecideFn,
    visits: list[WalkVisit],
    level: str,
) -> None:
    after: ReviewUnit | None = None
    while True:
        units = list_units(live.load(), level)
        index = 0 if after is None else _index_after(units, after)
        if index >= len(units):
            return
        after = _stay_loop(live, decide, units[index], visits)


def _stay_loop(
    live: LiveDocx,
    decide: DecideFn,
    seed: ReviewUnit,
    visits: list[WalkVisit],
) -> ReviewUnit:
    current = seed
    stay_index = 0
    while True:
        units = list_units(live.load(), current.level)
        unit = _same_unit(units, current)
        if unit is None:
            return current
        unit = unit.at_stay(stay_index)
        visits.append(
            WalkVisit(
                level=unit.level,
                node_id=unit.node_id,
                stay_index=unit.stay_index,
                text=unit.text,
            )
        )
        decision = decide(unit, live)
        if decision is StayOrGo.GO:
            return _refreshed_or_current(live, unit)
        if decision is not StayOrGo.STAY:
            raise TypeError(f"decide must return StayOrGo, got {decision!r}")
        current = _refreshed_or_current(live, unit)
        stay_index += 1


def _refreshed_or_current(live: LiveDocx, unit: ReviewUnit) -> ReviewUnit:
    return _same_unit(list_units(live.load(), unit.level), unit) or unit


def _same_unit(units: Sequence[ReviewUnit], seed: ReviewUnit) -> ReviewUnit | None:
    if seed.level == CALOSC:
        return units[0] if units else None
    by_text = [unit for unit in units if _same_container(unit, seed) and unit.text == seed.text]
    if len(by_text) == 1:
        return by_text[0]
    by_anchor = [
        unit for unit in units if _same_container(unit, seed) and unit.char_start == seed.char_start
    ]
    if len(by_anchor) == 1:
        return by_anchor[0]
    by_container = [unit for unit in units if _same_container(unit, seed)]
    if len(by_container) == 1:
        return by_container[0]
    return None


def _same_container(unit: ReviewUnit, seed: ReviewUnit) -> bool:
    if seed.level == ROZDZIAL:
        if seed.locator is not None and unit.locator == seed.locator:
            return True
        if seed.paragraph_locators and unit.paragraph_locators:
            return bool(set(seed.paragraph_locators) & set(unit.paragraph_locators))
        return False
    if seed.paragraph_locator is not None:
        return unit.paragraph_locator == seed.paragraph_locator
    if seed.locator is not None:
        return unit.locator == seed.locator
    return unit.node_id == seed.node_id


def _index_after(units: Sequence[ReviewUnit], finished: ReviewUnit) -> int:
    matched = _same_unit(units, finished)
    if matched is not None:
        return units.index(matched) + 1
    for index, unit in enumerate(units):
        if not _unit_before(unit, finished):
            return index
    return len(units)


def _unit_before(unit: ReviewUnit, ref: ReviewUnit) -> bool:
    return _order_key(unit) < _order_key(ref)


def _order_key(unit: ReviewUnit) -> tuple[tuple[str | int, ...], int]:
    locator = unit.paragraph_locator or unit.locator
    start = unit.char_start if unit.char_start is not None else -1
    return (_locator_key(locator), start)


def _locator_key(locator: str | None) -> tuple[str | int, ...]:
    if locator is None:
        return ()
    return tuple(int(part) if part.isdigit() else part for part in locator.split(":"))


def _body_paragraphs(document: ReviewDocument) -> tuple[ParagraphNode, ...]:
    return tuple(
        paragraph
        for paragraph in document.iter_paragraphs()
        if _reviewable_source(paragraph.metadata.get("source"))
    )


def _reviewable_source(source: str | None) -> bool:
    return source not in _STORY_SKIP and not (
        source is not None and source.startswith(("header-", "footer-"))
    )


def _body_section(section: SectionNode) -> bool:
    source = section.metadata.get("source")
    if not _reviewable_source(source):
        return False
    paragraphs = section.paragraphs
    skipped = all(
        not _reviewable_source(paragraph.metadata.get("source")) for paragraph in paragraphs
    )
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
        comments=_comments_on_span(comments, locator, sentence.physical_spans),
        physical_spans=sentence.physical_spans,
        document_sha256=sentence.document_sha256,
        geometry_coverage=sentence.geometry_coverage,
        geometry_diagnostics=sentence.geometry_diagnostics,
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
        physical_spans=paragraph.physical_spans,
        document_sha256=paragraph.document_sha256,
        geometry_coverage=paragraph.geometry_coverage,
        geometry_diagnostics=paragraph.geometry_diagnostics,
    )


def _chapter_unit(section: SectionNode, comments: Sequence[DocxComment]) -> ReviewUnit:
    locators = tuple(
        paragraph.locator for paragraph in section.paragraphs if paragraph.locator is not None
    )
    first = locators[0] if locators else section.locator
    physical_locators = {span.locator for span in section.physical_spans} or set(locators)
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
            if comment.locator in physical_locators
            or any(span.locator in physical_locators for span in comment.physical_spans)
        ),
        physical_spans=section.physical_spans,
        document_sha256=section.document_sha256,
        geometry_coverage=section.geometry_coverage,
        geometry_diagnostics=section.geometry_diagnostics,
    )


def _document_unit(document: ReviewDocument, comments: Sequence[DocxComment]) -> ReviewUnit:
    locators = tuple(span.locator for span in document.physical_spans)
    first = locators[0] if locators else None
    physical_locators = {span.locator for span in document.physical_spans}
    text = "\n\n".join(
        section.text
        for section in document.sections
        if section.physical_spans
        and all(span.locator in physical_locators for span in section.physical_spans)
        and section.text.strip()
    )
    return ReviewUnit(
        level=CALOSC,
        node_id=document.id,
        text=text,
        locator=first,
        paragraph_locator=first,
        paragraph_locators=locators,
        char_start=None,
        char_end=None,
        comments=tuple(
            comment
            for comment in comments
            if comment.locator in physical_locators
            or any(span.locator in physical_locators for span in comment.physical_spans)
        ),
        physical_spans=document.physical_spans,
        document_sha256=document.document_sha256,
        geometry_coverage=document.geometry_coverage,
        geometry_diagnostics=document.geometry_diagnostics,
    )


def _comments_on_span(
    comments: Sequence[DocxComment],
    locator: str | None,
    physical_spans: tuple[PhysicalCommentSpan, ...],
) -> tuple[DocxComment, ...]:
    matched = comments_for_locator(list(comments), locator)
    if len(physical_spans) != 1:
        return tuple(matched)
    start = physical_spans[0].start_offset
    end = physical_spans[0].end_offset
    sitting: list[DocxComment] = []
    for comment in matched:
        span = next((span for span in comment.physical_spans if span.locator == locator), None)
        comment_start = span.start_offset if span is not None else comment.start_offset
        comment_end = span.end_offset if span is not None else comment.end_offset
        if comment_start is None or comment_end is None:
            sitting.append(comment)
            continue
        if (comment_start == comment_end and start <= comment_start <= end) or (
            comment_start < end and comment_end > start
        ):
            sitting.append(comment)
    return tuple(sitting)


__all__ = [
    "DecideFn",
    "ReviewUnit",
    "StayOrGo",
    "WalkVisit",
    "list_units",
    "walk_live_docx",
]

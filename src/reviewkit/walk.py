"""Stay-or-go walk over one live DOCX: zdanie, then akapit, then rozdział, then całość."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256

from docxtor import (
    DocumentError,
    PhysicalCommentSpan,
    PhysicalParagraphGeometry,
    ReviewCoverage,
    ReviewDiagnostic,
)

from reviewkit.comments import DocxComment, comments_for_locator
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.levels import AKAPIT, CALOSC, ROZDZIAL, ZDANIE
from reviewkit.live_docx import LiveDocx
from reviewkit.parser_docx import document_from_projection
from reviewkit.regions import ReviewRegion, group_regions


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

    regions: tuple[ReviewRegion, ...] = ()

    def at_stay(self, stay_index: int) -> ReviewUnit:
        return replace(self, stay_index=stay_index)

    def with_regions(self, regions: tuple[ReviewRegion, ...]) -> ReviewUnit:
        return replace(
            self,
            regions=regions,
            physical_spans=regions[0].spans if len(regions) == 1 else (),
        )


@dataclass(frozen=True)
class WalkVisit:
    level: str
    node_id: str
    stay_index: int
    text: str


class ReviewEventKind(StrEnum):
    ENTERED = "entered"
    STAYED = "stayed"
    ADVANCED = "advanced"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ReviewEvent:
    kind: ReviewEventKind
    sequence: int
    level: str | None
    node_id: str | None
    stay_index: int
    before_sha256: str | None
    after_sha256: str | None
    created_comment_ids: tuple[str, ...] = ()


ReviewObserver = Callable[[ReviewEvent], None]


class ReviewTraversalError(RuntimeError):
    """A scope or original-text story could not be reviewed completely."""


@dataclass
class _WalkState:
    observer: ReviewObserver | None
    visits: list[WalkVisit]
    sequence: int = 0
    current: ReviewUnit | None = None
    digest: str | None = None
    before_comment_ids: frozenset[str] = frozenset()

    def emit(
        self,
        kind: ReviewEventKind,
        before: str | None,
        after: str | None,
        created: tuple[str, ...] = (),
    ) -> None:
        self.sequence += 1
        unit = self.current
        event = ReviewEvent(
            kind=kind,
            sequence=self.sequence,
            level=unit.level if unit else None,
            node_id=unit.node_id if unit else None,
            stay_index=unit.stay_index if unit else 0,
            before_sha256=before,
            after_sha256=after,
            created_comment_ids=created,
        )
        self.digest = after
        if self.observer is not None:
            self.observer(event)


def list_units(document: ReviewDocument, level: str) -> tuple[ReviewUnit, ...]:
    units = _list_units(document, level)
    return tuple(
        unit.with_regions(
            group_regions(unit.physical_spans, document.paragraph_stories)
            if unit.physical_spans
            else unit.regions
        )
        for unit in units
    )


def _list_units(document: ReviewDocument, level: str) -> tuple[ReviewUnit, ...]:
    comments = tuple(document.comments)
    if level == ZDANIE:
        return tuple(
            _sentence_unit(sentence, paragraph, comments)
            for paragraph in _review_paragraphs(document)
            for sentence in paragraph.sentences
        )
    if level == AKAPIT:
        return tuple(
            _paragraph_unit(paragraph, comments) for paragraph in _review_paragraphs(document)
        )
    if level == ROZDZIAL:
        return tuple(
            _chapter_unit(section, comments)
            for section in document.sections
            if _review_section(section)
        )
    if level == CALOSC:
        return (_document_unit(document, comments),)
    raise ValueError(f"unknown walk level: {level!r}")


DecideFn = Callable[[ReviewUnit, LiveDocx], StayOrGo]


def walk_live_docx(
    live: LiveDocx, decide: DecideFn, *, observer: ReviewObserver | None = None
) -> tuple[WalkVisit, ...]:
    """Walk every original story; only an explicit GO advances a scope."""
    state = _WalkState(observer, [])
    try:
        state.digest = _digest(live)
        state.before_comment_ids = frozenset(comment.id for comment in live.comments())
        for level in (ZDANIE, AKAPIT, ROZDZIAL, CALOSC):
            _walk_level(live, decide, state, level)
        state.current = None
        state.emit(ReviewEventKind.COMPLETED, state.digest, _digest(live))
    except (Exception, KeyboardInterrupt):
        try:
            after: str | None = _digest(live)
            created = tuple(
                comment.id
                for comment in live.comments()
                if comment.id not in state.before_comment_ids
            )
        except (OSError, DocumentError, ValueError):
            after, created = state.digest, ()
        state.emit(ReviewEventKind.INTERRUPTED, state.digest, after, created)
        raise
    return tuple(state.visits)


def _digest(live: LiveDocx) -> str:
    return sha256(live.open().to_bytes()).hexdigest()


def _validate_inventory(document: ReviewDocument, level: str) -> tuple[ReviewUnit, ...]:
    units = list_units(document, level)
    expected = set(
        document.original_text_paragraph_locators
        if level == ZDANIE
        else document.original_paragraph_locators
    )
    represented = {
        span.locator for unit in units for region in unit.regions for span in region.spans
    }
    missing = expected - represented
    if missing:
        raise ReviewTraversalError(
            f"{level} does not represent original-text paragraphs: {sorted(missing)!r}"
        )
    if document.geometry_coverage is not ReviewCoverage.COMPLETE:
        raise ReviewTraversalError("original DOCX physical inventory is incomplete")
    for unit in units:
        if unit.geometry_coverage is not ReviewCoverage.COMPLETE or not unit.regions:
            raise ReviewTraversalError(f"{level} scope {unit.node_id!r} has incomplete geometry")
    return units


def _walk_level(live: LiveDocx, decide: DecideFn, state: _WalkState, level: str) -> None:
    scopes = _validate_inventory(live.load(), level)
    for scope in scopes:
        _stay_loop(live, decide, scope, state)


def _stay_loop(live: LiveDocx, decide: DecideFn, seed: ReviewUnit, state: _WalkState) -> None:
    current = seed
    stay_index = 0
    while True:
        unit = _refresh_scope(live, current).at_stay(stay_index)
        state.current = unit
        before = _digest(live)
        before_ids = {comment.id for comment in live.comments()}
        state.before_comment_ids = frozenset(before_ids)
        state.emit(ReviewEventKind.ENTERED, before, before)
        state.visits.append(WalkVisit(unit.level, unit.node_id, stay_index, unit.text))
        decision = decide(unit, live)
        after = _digest(live)
        created = tuple(comment.id for comment in live.comments() if comment.id not in before_ids)
        if decision is StayOrGo.GO:
            _refresh_scope(live, unit)
            state.emit(ReviewEventKind.ADVANCED, before, after, created)
            state.before_comment_ids = frozenset(comment.id for comment in live.comments())
            return
        if decision is not StayOrGo.STAY:
            raise TypeError(f"decide must return StayOrGo, got {decision!r}")
        state.emit(ReviewEventKind.STAYED, before, after, created)
        state.before_comment_ids = frozenset(comment.id for comment in live.comments())
        current = unit
        stay_index += 1


def _refresh_scope(live: LiveDocx, unit: ReviewUnit) -> ReviewUnit:
    if unit.document_sha256 is None:
        raise ReviewTraversalError("current scope has no source snapshot")
    regions = tuple(
        ReviewRegion(
            region.story_id,
            live.open().map_review_spans(unit.document_sha256, region.spans),
        )
        for region in unit.regions
    )
    projection = live.open().project_review()
    geometry = projection.physical_geometry
    if geometry is None:
        raise ReviewTraversalError("current scope has no physical inventory")
    document = document_from_projection(projection, source_path=live.path)
    _validate_inventory(document, unit.level)
    paragraphs = {paragraph.locator: paragraph for paragraph in geometry.paragraphs}
    text_parts: list[str] = []
    coordinates: list[tuple[int, int]] = []
    spans = tuple(span for region in regions for span in region.spans)
    for region in regions:
        for span in region.spans:
            paragraph = paragraphs.get(span.locator)
            if (
                paragraph is None
                or paragraph.story_id != region.story_id
                or not paragraph.addressable
            ):
                raise ReviewTraversalError("captured scope lost its proven original story")
            start = _effective_offset(paragraph, span.start_offset)
            end = _effective_offset(paragraph, span.end_offset)
            text_parts.append(paragraph.effective_text[start:end].strip())
            leading = len(paragraph.effective_text) - len(paragraph.effective_text.lstrip())
            size = len(paragraph.effective_text.strip())
            coordinates.append(
                (min(size, max(0, start - leading)), min(size, max(0, end - leading)))
            )
    char_start, char_end = (
        coordinates[0] if unit.level in {ZDANIE, AKAPIT} and len(coordinates) == 1 else (None, None)
    )
    return replace(
        unit.with_regions(regions),
        text="\n\n".join(part for part in text_parts if part),
        char_start=char_start,
        char_end=char_end,
        comments=_comments_in_scope(document.comments, spans),
        document_sha256=geometry.document_sha256,
        geometry_coverage=geometry.coverage,
        geometry_diagnostics=geometry.diagnostics,
    )


def _effective_offset(paragraph: PhysicalParagraphGeometry, source_offset: int) -> int:
    return sum(
        max(0, min(source_offset, origin.source_end) - origin.source_start)
        for origin in paragraph.text_origins
    )


def _comments_in_scope(
    comments: Sequence[DocxComment], spans: tuple[PhysicalCommentSpan, ...]
) -> tuple[DocxComment, ...]:
    locators = {span.locator for span in spans}
    return tuple(
        comment
        for comment in comments
        if (not comment.physical_spans and comment.locator in locators)
        or any(
            target.locator == anchor.locator
            and (
                target.start_offset <= anchor.start_offset <= target.end_offset
                if anchor.start_offset == anchor.end_offset
                else target.start_offset < anchor.end_offset
                and anchor.start_offset < target.end_offset
            )
            for target in spans
            for anchor in comment.physical_spans
        )
    )


def _review_paragraphs(document: ReviewDocument) -> tuple[ParagraphNode, ...]:
    return tuple(
        paragraph
        for paragraph in document.iter_paragraphs()
        if _reviewable_source(paragraph.metadata.get("source"))
    )


def _reviewable_source(source: str | None) -> bool:
    return source != "comment"


def _review_section(section: SectionNode) -> bool:
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
    spans = tuple(span for region in document.regions for span in region.spans)
    locators = tuple(span.locator for span in spans)
    first = locators[0] if locators else None
    physical_locators = set(locators)
    return ReviewUnit(
        level=CALOSC,
        node_id=document.id,
        text=document.text,
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
        regions=document.regions,
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
    "ReviewEvent",
    "ReviewEventKind",
    "ReviewObserver",
    "ReviewTraversalError",
    "ReviewUnit",
    "StayOrGo",
    "WalkVisit",
    "list_units",
    "walk_live_docx",
]

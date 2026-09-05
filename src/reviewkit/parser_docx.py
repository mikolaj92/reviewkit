"""DOCX parser that builds the internal review hierarchy."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from docxtor import (
    AddressableSpan,
    DocumentError,
    DocxReviewProjection,
    ReviewCoverage,
    ReviewParagraphProjection,
    project_docx_for_review,
)

from reviewkit.comments import (
    DocxComment,
    _comment_markers_are_complete,
    _comment_thread_ids_are_complete,
    _project_comment,
    comments_for_locator,
)
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.markup_purity import has_tracked_revisions
from reviewkit.models import (
    RevisionCoverageState,
    RevisionLedger,
    SourceRevision,
    SourceRevisionKind,
)
from reviewkit.parser_text import split_sentences_with_spans


def split_sentences(text: str) -> list[str]:
    """Backward-compatible export of the shared format-neutral splitter."""
    return [sentence for sentence, _start, _end in split_sentences_with_spans(text)]


@dataclass(frozen=True)
class DocxDocumentParser:
    """DocumentParser adapter backed only by Docxtor's public projection API."""

    def parse(self, source: str | Path) -> ReviewDocument:
        return load_docx(source)


def load_docx(path: str | Path) -> ReviewDocument:
    source_path = Path(path)
    projection = project_docx_for_review(source_path)
    comments = [_project_comment(comment) for comment in projection.comments]
    effective_texts, revision_ledger = _project_revision_input(projection.spans)
    tracked_revisions = has_tracked_revisions(source_path)
    if (
        projection.coverage is ReviewCoverage.INCOMPLETE
        or _comment_ids_are_ambiguous(comments)
        or not _comment_markers_are_complete(source_path, comments)
        or not _comment_thread_ids_are_complete(source_path)
    ):
        revision_ledger = revision_ledger.model_copy(
            update={"coverage": RevisionCoverageState.INCOMPLETE}
        )

    # Section/paragraph id counters are shared across the body walk and the synthetic
    # header/footer sections so every node keeps a globally unique id. "s1" is reserved
    # for the implicit leading body section, so section numbering starts at 2.
    section_ids = itertools.count(2)
    paragraph_ids = itertools.count(1)

    sections: list[SectionNode] = []
    current = SectionNode(id="s1")

    # Docxtor owns mechanical addressing. Sort its body/table segments by the global
    # paragraph index so tables remain interleaved with surrounding body paragraphs.
    for segment in sorted(
        _iter_review_segments(projection.paragraphs, body=True),
        key=lambda item: item.paragraph_index if item.paragraph_index is not None else -1,
    ):
        locator = segment.locator
        source = _segment_source(locator)
        text = effective_texts.get(locator, segment.text).strip()
        if not text:
            continue

        if segment.is_heading:
            if current.title or current.paragraphs:
                sections.append(current)
                current = SectionNode(
                    id=f"s{next(section_ids)}",
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                )
            else:
                current = SectionNode(
                    id=current.id,
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                )
            continue

        current.paragraphs.append(
            _paragraph_node(
                f"p{next(paragraph_ids)}",
                text,
                current.id,
                locator,
                source,
                list(segment.opaque_ranges),
                comments_for_locator(comments, locator),
            )
        )

    if current.title or current.paragraphs or not sections:
        sections.append(current)

    # Header/footer paragraphs get their own synthetic sections keyed by source so they
    # are not misread as body prose tacked onto the trailing body section. Locator strings
    # ("header:S:p:P"/"footer:S:p:P") are unchanged, so rendering resolves them identically.
    sections.extend(
        _story_sections(
            projection,
            section_ids,
            paragraph_ids,
            comments,
            effective_texts,
        )
    )

    metadata = {
        "paragraph_count": str(sum(len(section.paragraphs) for section in sections)),
        "table_count": str(projection.table_count),
        "comment_count": str(len(comments)),
        "tracked_revisions_detected": str(tracked_revisions).lower(),
    }
    return ReviewDocument(
        source_path=source_path,
        sections=sections,
        metadata=metadata,
        comments=comments,
        revision_ledger=revision_ledger,
    )


def _project_revision_input(
    spans: tuple[AddressableSpan, ...],
) -> tuple[dict[str, str], RevisionLedger]:
    effective_parts: dict[str, list[str]] = {}
    entries: list[SourceRevision] = []
    coverage = RevisionCoverageState.COMPLETE
    for span in spans:
        locator = _reviewkit_locator(span.container_id)
        match span.role:
            case "insertion":
                effective_parts.setdefault(locator, []).append(span.text)
                entries.append(_source_revision(span, locator, SourceRevisionKind.INSERTED))
            case "deletion":
                entries.append(_source_revision(span, locator, SourceRevisionKind.DELETED))
            case "run":
                effective_parts.setdefault(locator, []).append(span.text)
            case "hyperlink":
                effective_parts.setdefault(locator, []).append(span.text)
                if span.revision_id is not None:
                    coverage = RevisionCoverageState.INCOMPLETE
            case unexpected:
                assert_never(unexpected)
    for entry in entries:
        effective_parts.setdefault(entry.locator, [])
    return (
        {locator: "".join(parts) for locator, parts in effective_parts.items()},
        RevisionLedger(coverage=coverage, entries=tuple(entries)),
    )


@dataclass(frozen=True)
class DocxFootnote:
    """One content footnote read from a ``.docx`` package: its ``w:id`` and visible text."""

    id: str
    text: str


def read_footnotes(path: str | Path) -> list[DocxFootnote]:
    try:
        projection = project_docx_for_review(path)
    except (OSError, DocumentError, ValueError):
        return []
    return [
        DocxFootnote(id=note.note_id, text=note.text)
        for note in projection.notes
        if note.kind == "footnote"
    ]


def _paragraph_node(
    paragraph_id: str,
    text: str,
    section_id: str,
    locator: str,
    source: str,
    opaque_ranges: list[tuple[int, int]] | None = None,
    comments: list[DocxComment] | None = None,
) -> ParagraphNode:
    sentences = [
        SentenceNode(
            id=f"{paragraph_id}.s{index}",
            text=sentence,
            paragraph_id=paragraph_id,
            char_start=start,
            char_end=end,
            locator=f"{locator}:s:{index - 1}",
            metadata={"source": source},
        )
        for index, (sentence, start, end) in enumerate(split_sentences_with_spans(text), start=1)
    ]
    return ParagraphNode(
        id=paragraph_id,
        text=text,
        section_id=section_id,
        locator=locator,
        metadata={"source": source},
        sentences=sentences,
        opaque_ranges=opaque_ranges or [],
        comments=comments or [],
    )


def _iter_review_segments(
    segments: tuple[ReviewParagraphProjection, ...], *, body: bool
) -> Iterator[ReviewParagraphProjection]:
    for segment in segments:
        locator = segment.locator
        is_body_story = locator.startswith(("body:", "table:"))
        if is_body_story is body:
            yield segment


def _segment_source(locator: str) -> str:
    return locator.split(":", 1)[0]


def _story_sections(
    projection: DocxReviewProjection,
    section_ids: Iterator[int],
    paragraph_ids: Iterator[int],
    comments: list[DocxComment],
    effective_texts: dict[str, str],
) -> list[SectionNode]:
    grouped: dict[str, list[ReviewParagraphProjection]] = {}
    for segment in _iter_review_segments(projection.paragraphs, body=False):
        locator = segment.locator
        source = _segment_source(locator)
        if source in {"comment", "footnote", "endnote"}:
            continue
        grouped.setdefault(source, []).append(segment)

    sections: list[SectionNode] = []
    for source, entries in grouped.items():
        non_empty = [
            segment
            for segment in entries
            if effective_texts.get(segment.locator, segment.text).strip()
        ]
        if not non_empty:
            continue
        section_id = f"s{next(section_ids)}"
        paragraphs: list[ParagraphNode] = []
        for segment in non_empty:
            locator = segment.locator
            paragraphs.append(
                _paragraph_node(
                    f"p{next(paragraph_ids)}",
                    effective_texts.get(locator, segment.text).strip(),
                    section_id,
                    locator,
                    source,
                    list(segment.opaque_ranges),
                    comments_for_locator(comments, locator),
                )
            )
        sections.append(
            SectionNode(
                id=section_id,
                title=None,
                metadata={"source": source},
                paragraphs=paragraphs,
            )
        )
    return sections


def _source_revision(
    span: AddressableSpan,
    locator: str,
    kind: SourceRevisionKind,
) -> SourceRevision:
    return SourceRevision(
        kind=kind,
        text=span.text,
        locator=locator,
        span_id=span.span_id,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        revision_id=span.revision_id,
        author=span.revision_author,
        date=span.revision_date,
    )


def _reviewkit_locator(container_id: str) -> str:
    parts = container_id.split(":")
    if len(parts) == 8 and parts[0] == "table" and parts[2] == "r" and parts[4] == "c":
        return f"table:{parts[1]}:row:{parts[3]}:cell:{parts[5]}:p:{parts[7]}"
    return container_id


def _comment_anchor_is_unresolved(comment: DocxComment, comments: list[DocxComment]) -> bool:
    """Return whether a source comment has no usable story anchor.

    Word replies normally have no range markers of their own. A reply is anchored through
    its parent comment when that parent has a stable locator; only an unanchored standalone
    comment (or a reply whose parent is missing/unanchored) makes revision coverage
    incomplete.
    """
    if comment.locator is not None:
        return False
    if comment.parent_id is None:
        return True
    parent = next((candidate for candidate in comments if candidate.id == comment.parent_id), None)
    return parent is None or parent.locator is None


def _comment_ids_are_ambiguous(comments: list[DocxComment]) -> bool:
    return len({comment.id for comment in comments}) != len(comments)

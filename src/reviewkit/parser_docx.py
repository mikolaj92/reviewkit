"""DOCX parser that builds the internal review hierarchy."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from pathlib import Path
from typing import assert_never

from docxtor import (
    AddressableSpan,
    DocumentError,
    DocxReviewProjection,
    PhysicalCommentSpan,
    PhysicalParagraphGeometry,
    ReviewCoverage,
    ReviewDiagnostic,
    ReviewParagraphProjection,
    physical_span_for_semantic_range,
    project_docx_for_review,
)

from reviewkit.comments import (
    DocxComment,
    comments_for_locator,
    comments_from_projection,
)
from reviewkit.document import (
    ParagraphNode,
    ReviewDocument,
    RevisionCoverageState,
    RevisionLedger,
    SectionNode,
    SentenceNode,
    SourceRevision,
    SourceRevisionKind,
)
from reviewkit.parser_text import split_sentences_with_spans


def load_docx(path: str | Path) -> ReviewDocument:
    source_path = Path(path)
    return document_from_projection(
        project_docx_for_review(source_path.read_bytes()), source_path=source_path
    )


def document_from_projection(
    projection: DocxReviewProjection, *, source_path: Path | None = None
) -> ReviewDocument:
    """Build the walk tree from one provider-owned immutable DOCX snapshot."""
    geometry = projection.physical_geometry
    if geometry is None:
        raise DocumentError("review projection has no physical geometry")
    physical_paragraphs = {paragraph.locator: paragraph for paragraph in geometry.paragraphs}
    comments = comments_from_projection(projection)
    effective_texts, revision_ledger = _project_revision_input(projection.spans)
    projected_marks = getattr(projection, "paragraph_mark_revisions", None)
    paragraph_marks = tuple(
        _source_revision(
            span,
            _reviewkit_locator(span.container_id),
            SourceRevisionKind.INSERTED if span.role == "insertion" else SourceRevisionKind.DELETED,
        ).model_copy(update={"paragraph_mark": True})
        for span in projected_marks or ()
    )
    revision_ledger = revision_ledger.model_copy(
        update={"entries": revision_ledger.entries + paragraph_marks}
    )
    tracked_revisions = projection.tracked_revisions_detected
    if (
        projection.coverage is ReviewCoverage.INCOMPLETE
        or geometry.coverage is ReviewCoverage.INCOMPLETE
        or (projected_marks is None and tracked_revisions)
        or _comment_ids_are_ambiguous(comments)
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
    current = SectionNode(
        id="s1",
        document_sha256=geometry.document_sha256,
        geometry_coverage=geometry.coverage,
        geometry_diagnostics=geometry.diagnostics,
    )

    # Docxtor owns mechanical addressing. Sort its body/table segments by the global
    # paragraph index so tables remain interleaved with surrounding body paragraphs.
    for segment in sorted(
        _iter_review_segments(projection.paragraphs, body=True),
        key=lambda item: item.paragraph_index if item.paragraph_index is not None else -1,
    ):
        locator = segment.locator
        source = _segment_source(locator)
        physical_span = _physical_span(physical_paragraphs, locator)
        text = effective_texts.get(locator, segment.text).strip()

        if segment.is_heading:
            if current.title or current.paragraphs or current.physical_spans:
                sections.append(current)
                current = SectionNode(
                    id=f"s{next(section_ids)}",
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                    document_sha256=geometry.document_sha256,
                    geometry_coverage=geometry.coverage,
                    geometry_diagnostics=geometry.diagnostics,
                )
            else:
                current = SectionNode(
                    id=current.id,
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                    physical_spans=current.physical_spans,
                    document_sha256=geometry.document_sha256,
                    geometry_coverage=geometry.coverage,
                    geometry_diagnostics=geometry.diagnostics,
                )
            current.physical_spans += (physical_span,)
            continue

        current.physical_spans += (physical_span,)
        if not text:
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
                physical_paragraph=physical_paragraphs[locator],
                projection=projection,
            )
        )

    if current.title or current.paragraphs or current.physical_spans or not sections:
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
        "document_sha256": geometry.document_sha256,
    }
    return ReviewDocument(
        source_path=source_path,
        sections=sections,
        metadata=metadata,
        comments=comments,
        revision_ledger=revision_ledger,
        physical_spans=tuple(
            paragraph.span
            for paragraph in geometry.paragraphs
            if paragraph.locator.startswith(("body:", "table:"))
        ),
        document_sha256=geometry.document_sha256,
        geometry_coverage=geometry.coverage,
        geometry_diagnostics=geometry.diagnostics,
    )


def _project_revision_input(
    spans: tuple[AddressableSpan, ...],
) -> tuple[dict[str, str], RevisionLedger]:
    effective_parts: dict[str, list[str]] = {}
    entries: list[SourceRevision] = []
    coverage = RevisionCoverageState.COMPLETE
    for span in spans:
        locator = _reviewkit_locator(span.container_id)
        effective = effective_parts.setdefault(span.container_id, [])
        match span.role:
            case "insertion":
                effective.append(span.text)
                entries.append(_source_revision(span, locator, SourceRevisionKind.INSERTED))
            case "deletion":
                entries.append(_source_revision(span, locator, SourceRevisionKind.DELETED))
            case "run":
                effective.append(span.text)
            case "hyperlink":
                effective.append(span.text)
                if span.revision_id is not None:
                    coverage = RevisionCoverageState.INCOMPLETE
            case unexpected:
                assert_never(unexpected)
    return (
        {locator: "".join(parts) for locator, parts in effective_parts.items()},
        RevisionLedger(coverage=coverage, entries=tuple(entries)),
    )


def _paragraph_node(
    paragraph_id: str,
    text: str,
    section_id: str,
    locator: str,
    source: str,
    opaque_ranges: list[tuple[int, int]] | None = None,
    comments: list[DocxComment] | None = None,
    *,
    physical_paragraph: PhysicalParagraphGeometry,
    projection: DocxReviewProjection,
) -> ParagraphNode:
    geometry = projection.physical_geometry
    if geometry is None:
        raise DocumentError("review projection has no physical geometry")
    sentences = []
    for index, (sentence, start, end) in enumerate(split_sentences_with_spans(text), start=1):
        spans, coverage, diagnostics = _semantic_range(
            physical_paragraph, text, start, end, sentence, geometry.coverage
        )
        sentences.append(
            SentenceNode(
                id=f"{paragraph_id}.s{index}",
                text=sentence,
                paragraph_id=paragraph_id,
                char_start=start,
                char_end=end,
                locator=f"{locator}:s:{index - 1}",
                metadata={"source": source},
                physical_spans=spans,
                document_sha256=geometry.document_sha256,
                geometry_coverage=coverage,
                geometry_diagnostics=geometry.diagnostics + diagnostics,
            )
        )
    spans, coverage, diagnostics = _semantic_range(
        physical_paragraph, text, 0, len(text), text, geometry.coverage
    )
    return ParagraphNode(
        id=paragraph_id,
        text=text,
        section_id=section_id,
        locator=locator,
        metadata={"source": source},
        sentences=sentences,
        opaque_ranges=opaque_ranges or [],
        comments=comments or [],
        physical_spans=spans,
        document_sha256=geometry.document_sha256,
        geometry_coverage=coverage,
        geometry_diagnostics=geometry.diagnostics + diagnostics,
    )


def _semantic_range(
    paragraph: PhysicalParagraphGeometry,
    semantic_text: str,
    start: int,
    end: int,
    expected_text: str,
    coverage: ReviewCoverage,
) -> tuple[tuple[PhysicalCommentSpan, ...], ReviewCoverage, tuple[ReviewDiagnostic, ...]]:
    try:
        span = physical_span_for_semantic_range(paragraph, semantic_text, start, end, expected_text)
    except ValueError as exc:
        return (
            (),
            ReviewCoverage.INCOMPLETE,
            (ReviewDiagnostic("unprojected_semantic_range", str(exc)),),
        )
    return (span,), coverage, ()


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


def _physical_span(
    paragraphs: dict[str, PhysicalParagraphGeometry], locator: str
) -> PhysicalCommentSpan:
    paragraph = paragraphs.get(locator)
    if paragraph is None:
        raise DocumentError(f"review paragraph {locator!r} has no physical projection")
    return paragraph.span


def _story_sections(
    projection: DocxReviewProjection,
    section_ids: Iterator[int],
    paragraph_ids: Iterator[int],
    comments: list[DocxComment],
    effective_texts: dict[str, str],
) -> list[SectionNode]:
    geometry = projection.physical_geometry
    if geometry is None:
        raise DocumentError("review projection has no physical geometry")
    physical_paragraphs = {paragraph.locator: paragraph for paragraph in geometry.paragraphs}
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
                    physical_paragraph=physical_paragraphs[locator],
                    projection=projection,
                )
            )
        sections.append(
            SectionNode(
                id=section_id,
                title=None,
                metadata={"source": source},
                paragraphs=paragraphs,
                physical_spans=tuple(
                    _physical_span(physical_paragraphs, segment.locator) for segment in entries
                ),
                document_sha256=geometry.document_sha256,
                geometry_coverage=geometry.coverage,
                geometry_diagnostics=geometry.diagnostics,
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


def _comment_ids_are_ambiguous(comments: list[DocxComment]) -> bool:
    return len({comment.id for comment in comments}) != len(comments)

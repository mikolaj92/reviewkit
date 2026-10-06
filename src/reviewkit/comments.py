"""Review-semantic projection of Docxtor's proven comment geometry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docxtor import (
    AddressableComment,
    DocumentError,
    DocxDocument,
    DocxReviewProjection,
    PhysicalCommentAnchor,
    PhysicalCommentSpan,
    ReviewCoverage,
    ReviewDiagnostic,
    project_docx_for_review,
)


@dataclass(frozen=True)
class DocxComment:
    id: str
    author: str
    initials: str
    text: str
    locator: str | None = None
    anchor_text: str = ""
    parent_id: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    # Keep legacy content equality; callers authorize geometry using these fields.
    end_locator: str | None = field(default=None, compare=False)
    physical_spans: tuple[PhysicalCommentSpan, ...] = field(default=(), compare=False)
    document_sha256: str | None = field(default=None, compare=False)
    geometry_coverage: ReviewCoverage = field(default=ReviewCoverage.INCOMPLETE, compare=False)
    geometry_diagnostics: tuple[ReviewDiagnostic, ...] = field(default=(), compare=False)

    @property
    def addressable(self) -> bool:
        """Whether Docxtor proved a physical anchor for this source snapshot."""
        return (
            self.geometry_coverage is ReviewCoverage.COMPLETE
            and bool(self.physical_spans)
            and bool(self.document_sha256)
        )


def read_comments(path: str | Path, *, strict: bool = False) -> list[DocxComment]:
    """Read comments; use ``strict=True`` when failure must not mean no comments.

    The tolerant default preserves the existing convenience API. The review walk
    and live handle use the strict projection path directly.
    """
    try:
        return comments_from_projection(project_docx_for_review(Path(path).read_bytes()))
    except (OSError, DocumentError, ValueError):
        if strict:
            raise
        return []


def comments_from_document(document: DocxDocument) -> list[DocxComment]:
    return comments_from_projection(document.project_review())


def comments_from_projection(projection: DocxReviewProjection) -> list[DocxComment]:
    geometry = projection.physical_geometry
    if geometry is None:
        raise DocumentError("review projection has no physical geometry")
    anchors = {anchor.comment_id: anchor for anchor in geometry.comment_anchors}
    return [
        _project_comment(comment, anchors.get(comment.comment_id), geometry.document_sha256)
        for comment in projection.comments
    ]


def comments_for_locator(comments: list[DocxComment], locator: str | None) -> list[DocxComment]:
    if not locator:
        return []
    return [
        comment
        for comment in comments
        if comment.locator == locator
        or any(span.locator == locator for span in comment.physical_spans)
    ]


def _project_comment(
    comment: AddressableComment,
    anchor: PhysicalCommentAnchor | None,
    document_sha256: str,
) -> DocxComment:
    trusted = (
        anchor is not None and anchor.addressable and anchor.document_sha256 == document_sha256
    )
    spans: tuple[PhysicalCommentSpan, ...] = anchor.spans if anchor is not None and trusted else ()
    # Scalar offsets describe exactly one paragraph, including a proven point.
    # A multi-paragraph range retains its endpoints and ordered physical spans.
    single_span = spans[0] if len(spans) == 1 else None
    return DocxComment(
        id=comment.comment_id,
        author=comment.author or "",
        initials=comment.initials or "",
        text=comment.text,
        locator=anchor.start_locator if spans and anchor is not None else comment.locator,
        anchor_text=comment.anchor_text,
        parent_id=comment.parent_id,
        start_offset=single_span.start_offset if single_span is not None else None,
        end_offset=single_span.end_offset if single_span is not None else None,
        end_locator=anchor.end_locator if anchor is not None else None,
        physical_spans=spans,
        document_sha256=document_sha256,
        geometry_coverage=(
            anchor.coverage
            if anchor is not None and anchor.document_sha256 == document_sha256
            else ReviewCoverage.INCOMPLETE
        ),
        geometry_diagnostics=(
            anchor.diagnostics
            if anchor is not None and anchor.document_sha256 == document_sha256
            else (
                ReviewDiagnostic(
                    "unprojected_comment_anchor",
                    f"Comment {comment.comment_id!r} has no matching physical anchor projection.",
                ),
            )
        ),
    )

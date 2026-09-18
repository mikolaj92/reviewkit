"""Review-semantic projection of Docxtor comment inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docxtor import (
    AddressableComment,
    DocumentError,
    DocxDocument,
    ReviewCoverage,
    inventory_review_markup,
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


def read_comments(path: str | Path) -> list[DocxComment]:
    try:
        return comments_from_document(DocxDocument.open(path))
    except (OSError, DocumentError, ValueError):
        return []


def comments_from_document(document: DocxDocument) -> list[DocxComment]:
    return [
        _project_comment(comment, _host_paragraph_text(document, comment.locator))
        for comment in document.comments
    ]


def comments_for_locator(comments: list[DocxComment], locator: str | None) -> list[DocxComment]:
    return [] if not locator else [comment for comment in comments if comment.locator == locator]


def _project_comment(comment: AddressableComment, paragraph_text: str = "") -> DocxComment:
    start, end = _unique_range(paragraph_text, comment.anchor_text)
    return DocxComment(
        comment.comment_id,
        comment.author or "",
        comment.initials or "",
        comment.text,
        comment.locator,
        comment.anchor_text,
        comment.parent_id,
        start,
        end,
    )


def _host_paragraph_text(document: DocxDocument, locator: str | None) -> str:
    if not locator:
        return ""
    paragraph = document.resolve_paragraph(locator)
    return paragraph.text if paragraph is not None else ""


def _unique_range(paragraph_text: str, anchor_text: str) -> tuple[int | None, int | None]:
    if not paragraph_text or not anchor_text:
        return (None, None)
    start = paragraph_text.find(anchor_text)
    if start < 0:
        return (None, None)
    if paragraph_text.find(anchor_text, start + 1) >= 0:
        return (None, None)
    return (start, start + len(anchor_text))


def _comment_markers_are_complete(path: str | Path, comments: list[DocxComment]) -> bool:
    inventory = inventory_review_markup(Path(path).read_bytes())
    return inventory.coverage is ReviewCoverage.COMPLETE and len({c.id for c in comments}) == len(
        comments
    )


def _comment_thread_ids_are_complete(path: str | Path) -> bool:
    inventory = inventory_review_markup(Path(path).read_bytes())
    return inventory.coverage is ReviewCoverage.COMPLETE

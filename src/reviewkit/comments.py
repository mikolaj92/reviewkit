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


def read_comments(path: str | Path) -> list[DocxComment]:
    try:
        return comments_from_document(DocxDocument.open(path))
    except (OSError, DocumentError, ValueError):
        return []


def comments_from_document(document: DocxDocument) -> list[DocxComment]:
    return [_project_comment(comment) for comment in document.comments]


def comments_for_locator(comments: list[DocxComment], locator: str | None) -> list[DocxComment]:
    return [] if not locator else [comment for comment in comments if comment.locator == locator]


def _project_comment(comment: AddressableComment) -> DocxComment:
    return DocxComment(
        comment.comment_id,
        comment.author or "",
        comment.initials or "",
        comment.text,
        comment.locator,
        comment.anchor_text,
        comment.parent_id,
    )


def _comment_markers_are_complete(path: str | Path, comments: list[DocxComment]) -> bool:
    inventory = inventory_review_markup(Path(path).read_bytes())
    return inventory.coverage is ReviewCoverage.COMPLETE and len({c.id for c in comments}) == len(
        comments
    )


def _comment_thread_ids_are_complete(path: str | Path) -> bool:
    inventory = inventory_review_markup(Path(path).read_bytes())
    return inventory.coverage is ReviewCoverage.COMPLETE

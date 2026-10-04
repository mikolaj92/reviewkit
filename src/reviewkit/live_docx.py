"""Same-file DOCX side effects for an in-progress review walk."""

from __future__ import annotations

from pathlib import Path

from docxtor import (
    CommentAuthor,
    CommentMutationError,
    CommentRange,
    DocumentError,
    DocxDocument,
    PublishError,
    SegmentReplacement,
    add_comment,
    publish_docx,
    remove_comments,
)

from reviewkit.comments import DocxComment, read_comments
from reviewkit.document import ReviewDocument
from reviewkit.parser_docx import load_docx


class LiveDocxError(RuntimeError):
    """A same-file DOCX mutation could not be applied."""


class LiveDocx:
    """The DOCX under review. Mutations write this path during the walk."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> ReviewDocument:
        return load_docx(self.path)

    def comments(self) -> list[DocxComment]:
        return read_comments(self.path)

    def comment(self, comment_id: str) -> DocxComment:
        for comment in self.comments():
            if comment.id == comment_id:
                return comment
        raise LiveDocxError(f"unknown comment {comment_id!r}")

    def add_comment(
        self,
        *,
        locator: str,
        start: int,
        end: int,
        text: str,
        expected_text: str | None = None,
        author: str = "Reviewer",
        initials: str = "RV",
    ) -> str:
        try:
            result = add_comment(
                self.path.read_bytes(),
                CommentRange(locator, start, end, expected_text),
                text,
                CommentAuthor(author=author, initials=initials),
            )
            created = result.receipt.created_ids
            if not created:
                raise LiveDocxError("add comment produced no comment id")
            publish_docx(result.data, self.path)
        except (OSError, DocumentError, CommentMutationError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc
        return created[0]

    def update_comment(self, comment_id: str, text: str) -> str:
        existing = self.comment(comment_id)
        if existing.locator is None or existing.start_offset is None or existing.end_offset is None:
            raise LiveDocxError(f"comment {comment_id!r} has no range to update")
        locator = existing.locator
        start = existing.start_offset
        end = existing.end_offset
        expected = existing.anchor_text or None
        author = existing.author or "Reviewer"
        initials = existing.initials or "RV"
        self.delete_comment(comment_id)
        return self.add_comment(
            locator=locator,
            start=start,
            end=end,
            text=text,
            expected_text=expected,
            author=author,
            initials=initials,
        )

    def delete_comment(self, comment_id: str) -> None:
        try:
            result = remove_comments(self.path.read_bytes(), {comment_id})
            publish_docx(result.data, self.path)
        except (OSError, DocumentError, CommentMutationError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc

    def change_text(self, *, locator: str, start: int, end: int, replacement: str) -> None:
        try:
            document = DocxDocument.open(self.path)
            document.apply_replacements(
                [
                    SegmentReplacement(
                        container_id=locator,
                        text=replacement,
                        start_offset=start,
                        end_offset=end,
                    )
                ],
                strict=True,
            )
            document.publish(self.path)
        except (OSError, DocumentError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc


__all__ = ["LiveDocx", "LiveDocxError"]

"""In-place side effects on the one DOCX the review is walking.

Every mutation publishes back to the same path. Docxtor owns the physical
write; this module only names review side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docxtor import (
    CommentAuthor,
    CommentMutationError,
    CommentRange,
    DocxDocument,
    SegmentReplacement,
    add_comment,
    publish_docx,
    remove_comments,
)

from reviewkit.comments import DocxComment, comments_from_document


class DocxReviewError(RuntimeError):
    """A same-file DOCX side effect could not be applied."""


@dataclass(frozen=True)
class LiveDocx:
    """The file under review. Side effects land here during the walk."""

    path: Path
    author: str = "Reviewer"
    initials: str = "RV"

    def comments(self) -> list[DocxComment]:
        return comments_from_document(DocxDocument.open(self.path))

    def add_comment(
        self,
        locator: str,
        start_offset: int,
        end_offset: int,
        text: str,
        *,
        expected_text: str | None = None,
    ) -> str:
        before = self.path.read_bytes()
        try:
            result = add_comment(
                before,
                CommentRange(locator, start_offset, end_offset, expected_text),
                text,
                CommentAuthor(self.author, self.initials),
            )
        except (CommentMutationError, ValueError) as exc:
            raise DocxReviewError(str(exc)) from exc
        created = result.receipt.created_ids
        if not created:
            raise DocxReviewError("comment add was not confirmed")
        publish_docx(result.data, self.path, source=before)
        return created[0]

    def update_comment(self, comment_id: str, text: str) -> None:
        if not text:
            raise DocxReviewError("comment text must not be empty")
        before = self.path.read_bytes()
        document = DocxDocument.open_bytes(before, filename=self.path.name)
        comment = next(
            (item for item in document.comments if item.comment_id == comment_id),
            None,
        )
        if comment is None:
            raise DocxReviewError(f"unknown comment id {comment_id!r}")
        try:
            document.apply_replacements(
                [SegmentReplacement(container_id=comment.container_id, text=text)],
                strict=True,
            )
        except ValueError as exc:
            raise DocxReviewError(str(exc)) from exc
        publish_docx(document.to_bytes(), self.path, source=before)

    def delete_comment(self, comment_id: str) -> None:
        before = self.path.read_bytes()
        try:
            result = remove_comments(before, {comment_id})
        except (CommentMutationError, ValueError) as exc:
            raise DocxReviewError(str(exc)) from exc
        publish_docx(result.data, self.path, source=before)

    def change_text(
        self,
        locator: str,
        start_offset: int,
        end_offset: int,
        replacement: str,
    ) -> None:
        before = self.path.read_bytes()
        document = DocxDocument.open_bytes(before, filename=self.path.name)
        try:
            document.apply_replacements(
                [
                    SegmentReplacement(
                        container_id=locator,
                        text=replacement,
                        start_offset=start_offset,
                        end_offset=end_offset,
                    )
                ],
                strict=True,
            )
        except ValueError as exc:
            raise DocxReviewError(str(exc)) from exc
        publish_docx(document.to_bytes(), self.path, source=before)


__all__ = ["DocxReviewError", "LiveDocx"]

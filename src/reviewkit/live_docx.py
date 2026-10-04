"""Same-file DOCX side effects for an in-progress review walk.

Docxtor is the Word layer. ReviewKit holds one open DOCX handle and asks
it to add / update / delete a comment, or to tracked-insert / delete /
replace text. It does not invent markup.
"""

from __future__ import annotations

from pathlib import Path

from docxtor import (
    CommentAuthor,
    CommentMutationError,
    CommentRange,
    DocumentError,
    DocxDocument,
    PublishError,
    RevisionAuthor,
    RevisionPosition,
    RevisionRange,
    add_paragraph_comment,
)

from reviewkit.comments import DocxComment, comments_from_document
from reviewkit.document import ReviewDocument
from reviewkit.parser_docx import load_docx


class LiveDocxError(RuntimeError):
    """A same-file DOCX mutation could not be applied."""


class LiveDocx:
    """The DOCX under review. One open Docxtor handle; mutations write this path."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._document = DocxDocument.open(self.path)

    def open(self) -> DocxDocument:
        return self._document

    def load(self) -> ReviewDocument:
        return load_docx(self.path)

    def comments(self) -> list[DocxComment]:
        return comments_from_document(self._document)

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
        """Add a Word comment on ``locator[start:end]``.

        A later stay may add another comment on the same sentence. Existing
        range markers make a second identical span opaque, so that extra
        comment is placed on the paragraph and still sits on the sentence.
        """
        writer = CommentAuthor(author=author, initials=initials)
        try:
            try:
                result = self._document.add_comment(
                    CommentRange(locator, start, end, expected_text), text, writer
                )
            except (CommentMutationError, IndexError):
                result = add_paragraph_comment(self._document.to_bytes(), locator, text, writer)
                self._document._adopt_bytes(result.data)
            created = result.receipt.created_ids
            if not created:
                raise LiveDocxError("add comment produced no comment id")
            self._publish()
        except (OSError, DocumentError, CommentMutationError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc
        return created[0]

    def update_comment(self, comment_id: str, text: str) -> str:
        """Change the body of an existing Word comment. Range markers stay."""
        try:
            self._document.update_comment(comment_id, text)
            self._publish()
        except (OSError, DocumentError, CommentMutationError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc
        return comment_id

    def delete_comment(self, comment_id: str) -> None:
        try:
            self._document.delete_comment(comment_id)
            self._publish()
        except (OSError, DocumentError, CommentMutationError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc

    def replace_text(
        self,
        *,
        locator: str,
        start: int,
        end: int,
        replacement: str,
        expected_text: str | None = None,
        author: str = "Reviewer",
    ) -> None:
        """Change a span as a Word tracked replace (w:del + w:ins)."""
        try:
            self._document.replace_revision(
                RevisionRange(locator, start, end, expected_text),
                replacement,
                RevisionAuthor(author=author),
            )
            self._publish()
        except (OSError, DocumentError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc

    def delete_text(
        self,
        *,
        locator: str,
        start: int,
        end: int,
        expected_text: str | None = None,
        author: str = "Reviewer",
    ) -> None:
        """Delete a span as a Word tracked deletion (w:del)."""
        try:
            self._document.delete_revision(
                RevisionRange(locator, start, end, expected_text),
                RevisionAuthor(author=author),
            )
            self._publish()
        except (OSError, DocumentError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc

    def insert_text(
        self,
        *,
        locator: str,
        offset: int,
        text: str,
        author: str = "Reviewer",
    ) -> None:
        """Insert text in an akapit as a Word tracked insertion (w:ins)."""
        try:
            self._document.insert_revision(
                RevisionPosition(locator, offset),
                text,
                RevisionAuthor(author=author),
            )
            self._publish()
        except (OSError, DocumentError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc

    def _publish(self) -> None:
        self._document.publish()


__all__ = ["LiveDocx", "LiveDocxError"]

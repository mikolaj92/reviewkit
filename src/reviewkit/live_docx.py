"""Same-file DOCX side effects for an in-progress review walk.

Docxtor is the Word layer. This module opens that handle and asks it for
comments and tracked insert / delete / replace. It does not invent markup.
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
    SegmentReplacement,
    add_comment,
    add_paragraph_comment,
    delete_revision,
    insert_revision,
    publish_docx,
    remove_comments,
    replace_revision,
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

    def open(self) -> DocxDocument:
        return DocxDocument.open(self.path)

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
        """Add a Word comment on ``locator[start:end]``.

        A later stay may add another comment on the same sentence. Existing
        range markers make a second identical span opaque, so that extra
        comment is placed on the paragraph and still sits on the sentence.
        """
        writer = CommentAuthor(author=author, initials=initials)
        data = self.path.read_bytes()
        try:
            try:
                result = add_comment(
                    data, CommentRange(locator, start, end, expected_text), text, writer
                )
            except (CommentMutationError, IndexError):
                result = add_paragraph_comment(data, locator, text, writer)
            created = result.receipt.created_ids
            if not created:
                raise LiveDocxError("add comment produced no comment id")
            publish_docx(result.data, self.path)
        except (OSError, DocumentError, CommentMutationError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc
        return created[0]

    def update_comment(self, comment_id: str, text: str) -> str:
        """Change the body of an existing Word comment. Range markers stay."""
        document = self.open()
        existing = next(
            (comment for comment in document.comments if comment.comment_id == comment_id),
            None,
        )
        if existing is None:
            raise LiveDocxError(f"unknown comment {comment_id!r}")
        try:
            document.apply_replacements(
                [SegmentReplacement(container_id=existing.container_id, text=text)],
                strict=True,
            )
            document.publish(self.path)
        except (OSError, DocumentError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc
        return comment_id

    def delete_comment(self, comment_id: str) -> None:
        try:
            result = remove_comments(self.path.read_bytes(), {comment_id})
            publish_docx(result.data, self.path)
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
            _deleted, inserted = replace_revision(
                self.path.read_bytes(),
                RevisionRange(locator, start, end, expected_text),
                replacement,
                RevisionAuthor(author=author),
            )
            publish_docx(inserted.data, self.path)
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
            result = delete_revision(
                self.path.read_bytes(),
                RevisionRange(locator, start, end, expected_text),
                RevisionAuthor(author=author),
            )
            publish_docx(result.data, self.path)
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
            result = insert_revision(
                self.path.read_bytes(),
                RevisionPosition(locator, offset),
                text,
                RevisionAuthor(author=author),
            )
            publish_docx(result.data, self.path)
        except (OSError, DocumentError, PublishError, ValueError) as exc:
            raise LiveDocxError(str(exc)) from exc


__all__ = ["LiveDocx", "LiveDocxError"]

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docxtor import (
    BodyAppendix,
    PublicationMarkError,
    append_body_appendix,
    has_body_appendix,
    remove_body_appendix,
    write_publication_bytes,
)

from docxtor import inventory_review_markup


class PortableReviewTrailError(ValueError):
    """Portable review trail could not be projected or transformed."""


@dataclass(frozen=True)
class PortableReviewTrailProfile:
    heading: str
    intro: str
    fallback_author: str = "Reviewer"


def has_portable_review_trail(
    source: str | Path | bytes, *, profile: PortableReviewTrailProfile
) -> bool:
    try:
        return has_body_appendix(source, heading=profile.heading)
    except PublicationMarkError as exc:
        raise PortableReviewTrailError(str(exc)) from exc


def append_portable_review_trail(
    source: str | Path | bytes, *, profile: PortableReviewTrailProfile
) -> bytes:
    try:
        if has_body_appendix(source, heading=profile.heading):
            raise PortableReviewTrailError("reviewed DOCX already carries a portable review trail")
        inventory = inventory_review_markup(
            source if isinstance(source, bytes) else Path(source).read_bytes()
        )
        comments = tuple(
            comment for comment in inventory.comments if comment.text and comment.text.strip()
        )
        if not comments:
            if inventory.comments:
                raise PortableReviewTrailError(
                    "reviewed DOCX has comments but no visible remark text"
                )
            return source if isinstance(source, bytes) else Path(source).read_bytes()
        paragraphs = (profile.intro,) + tuple(
            f"{index}. [{comment.author.strip() or profile.fallback_author}] {comment.text.strip()}"
            for index, comment in enumerate(comments, start=1)
        )
        return append_body_appendix(source, BodyAppendix(profile.heading, paragraphs))
    except PublicationMarkError as exc:
        raise PortableReviewTrailError(str(exc)) from exc


def strip_portable_review_trail(
    source: str | Path | bytes, *, profile: PortableReviewTrailProfile
) -> tuple[bytes, bool]:
    try:
        return remove_body_appendix(source, heading=profile.heading)
    except PublicationMarkError as exc:
        raise PortableReviewTrailError(str(exc)) from exc


def write_portable_review_trail(path: str | Path, data: bytes) -> Path:
    return write_publication_bytes(path, data)

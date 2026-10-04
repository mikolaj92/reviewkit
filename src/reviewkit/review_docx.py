"""Review one DOCX by walking that same file.

This is the library's primary review: zdanie, then akapit, then rozdział, then
całość n times. Each level uses a stay-or-go loop. Side effects write the file
under review; the walk does not judge an abstract copy and emit a different
DOCX only at the end.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from reviewkit.live_docx import LiveDocx
from reviewkit.walk import DecideFn, ReviewUnit, StayOrGo, WalkVisit, walk_live_docx


class DocxReviewer(Protocol):
    def decide(self, unit: ReviewUnit, docx: LiveDocx) -> StayOrGo: ...


@dataclass(frozen=True)
class DocxReview:
    """Outcome of walking one DOCX in place."""

    path: Path
    visits: tuple[WalkVisit, ...]


def review_docx(
    path: str | Path,
    reviewer: DocxReviewer | Callable[[ReviewUnit, LiveDocx], StayOrGo],
    *,
    calosc_times: int = 1,
    max_stays: int = 64,
) -> DocxReview:
    """Review ``path`` by walking that file. Mutations land on ``path``."""
    live = LiveDocx(path)
    raw = getattr(reviewer, "decide", reviewer)
    if not callable(raw):
        raise TypeError("reviewer must be callable or provide decide(unit, docx)")
    visits = walk_live_docx(
        live,
        cast(DecideFn, raw),
        calosc_times=calosc_times,
        max_stays=max_stays,
    )
    return DocxReview(path=live.path, visits=visits)


__all__ = ["DocxReview", "DocxReviewer", "review_docx"]

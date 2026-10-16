"""Story-bounded physical regions of a live review scope."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from docxtor import PhysicalCommentSpan


@dataclass(frozen=True)
class ReviewRegion:
    story_id: str
    spans: tuple[PhysicalCommentSpan, ...]


def group_regions(
    spans: Iterable[PhysicalCommentSpan], stories: Mapping[str, str]
) -> tuple[ReviewRegion, ...]:
    grouped: dict[str, list[PhysicalCommentSpan]] = {}
    for span in spans:
        grouped.setdefault(stories[span.locator], []).append(span)
    return tuple(ReviewRegion(story, tuple(parts)) for story, parts in grouped.items())

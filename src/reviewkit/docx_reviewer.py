"""Host decisions for the one-DOCX stay-or-go walk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reviewkit.docx_units import Jednostka
from reviewkit.stay_or_go import Ruch


@dataclass(frozen=True)
class AddComment:
    text: str
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True)
class UpdateComment:
    comment_id: str
    text: str


@dataclass(frozen=True)
class DeleteComment:
    comment_id: str


@dataclass(frozen=True)
class ChangeText:
    original: str
    replacement: str


SideEffect = AddComment | UpdateComment | DeleteComment | ChangeText


@dataclass(frozen=True)
class ReviewDecision:
    """Stay on this unit, or go to the next. Side effects are optional."""

    ruch: Ruch
    effects: tuple[SideEffect, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ruch", Ruch(self.ruch))
        object.__setattr__(self, "effects", tuple(self.effects))


class DocxReviewer(Protocol):
    """Host that, on a unit of the live file, stays or goes."""

    def consider(self, unit: Jednostka) -> ReviewDecision: ...


__all__ = [
    "AddComment",
    "ChangeText",
    "DeleteComment",
    "DocxReviewer",
    "ReviewDecision",
    "SideEffect",
    "UpdateComment",
]

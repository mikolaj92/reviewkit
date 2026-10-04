"""One visit of one unit on the live DOCX, and the decision that follows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from reviewkit.comments import DocxComment
from reviewkit.poziom import Poziom
from reviewkit.stay import StayOrGo


class EffectKind(StrEnum):
    ADD_COMMENT = "add_comment"
    UPDATE_COMMENT = "update_comment"
    DELETE_COMMENT = "delete_comment"
    CHANGE_TEXT = "change_text"


@dataclass(frozen=True)
class Effect:
    kind: EffectKind
    comment_id: str | None = None
    comment: str | None = None
    original_text: str | None = None
    replacement_text: str | None = None
    author: str | None = None
    initials: str | None = None


@dataclass(frozen=True)
class Unit:
    poziom: Poziom
    key: str
    node_id: str
    text: str
    locator: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    comments: tuple[DocxComment, ...] = ()


@dataclass(frozen=True)
class Visit:
    """What the reviewer sees: this unit, on this same file, this iteration."""

    unit: Unit
    visit_index: int
    path: Path


@dataclass(frozen=True)
class VisitDecision:
    stay_or_go: StayOrGo
    effects: tuple[Effect, ...] = ()


@runtime_checkable
class DocxReviewer(Protocol):
    """Host plugin for one visit of one unit on the live DOCX."""

    def visit(self, visit: Visit) -> VisitDecision: ...


class MockDocxReviewer:
    """Scriptable fake. Each ``visit`` pops the next decision."""

    def __init__(self, decisions: Sequence[VisitDecision] | None = None) -> None:
        self._decisions = list(decisions or [])
        self.visits: list[Visit] = []

    def visit(self, visit: Visit) -> VisitDecision:
        self.visits.append(visit)
        if self._decisions:
            return self._decisions.pop(0)
        return VisitDecision(stay_or_go=StayOrGo.GO)


__all__ = [
    "DocxReviewer",
    "Effect",
    "EffectKind",
    "MockDocxReviewer",
    "Unit",
    "Visit",
    "VisitDecision",
]

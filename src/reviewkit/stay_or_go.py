"""Stay-or-go loop used at every review level.

On a unit, decide: go to the next unit, or stay and iterate this same unit
again. The loop itself does not know about DOCX, comments, or text.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class Ruch(StrEnum):
    STAY = "stay"
    GO = "go"


class StayOrGoError(RuntimeError):
    """The stay-or-go loop refused to continue."""


def stay_or_go(
    consider: Callable[[int], T],
    *,
    is_go: Callable[[T], bool],
    max_visits: int = 32,
) -> Iterator[T]:
    """Yield ``consider(visit)`` until the decision is go.

    ``visit`` is 1-based. Staying forever raises :class:`StayOrGoError`.
    """
    if max_visits < 1:
        raise StayOrGoError("max_visits must be at least 1")
    visit = 1
    while True:
        if visit > max_visits:
            raise StayOrGoError(f"stayed on the same unit for {max_visits} visits")
        decision = consider(visit)
        yield decision
        if is_go(decision):
            return
        visit += 1


__all__ = ["Ruch", "StayOrGoError", "stay_or_go"]

"""Stay-or-go loop: iterate the same unit until the decision is go."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from reviewkit.models import ReviewBoundError, ReviewFailureClass


class StayOrGo(StrEnum):
    STAY = "stay"
    GO = "go"


def stay_loop(
    step: Callable[[int], StayOrGo],
    *,
    max_stays: int,
    node_id: str,
) -> int:
    """Run ``step(visit_index)`` until it returns go.

    ``visit_index`` is 0 for the first visit. Each stay repeats the same unit.
    Returns the number of visits performed.
    """
    if max_stays < 1:
        raise ReviewBoundError(
            failure_class=ReviewFailureClass.UNSUPPORTED_SHAPE,
            node_id=node_id,
            budget=max_stays,
            reason="max_stays must be positive",
        )
    visit_index = 0
    while True:
        decision = step(visit_index)
        visit_index += 1
        if decision is StayOrGo.GO:
            return visit_index
        if visit_index >= max_stays:
            raise ReviewBoundError(
                failure_class=ReviewFailureClass.UNSUPPORTED_SHAPE,
                node_id=node_id,
                budget=max_stays,
                retry_count=visit_index,
                reason="stay exceeded max_stays",
            )


__all__ = ["StayOrGo", "stay_loop"]

"""Per-fragment review courses: one frozen row after each visit."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from reviewkit.models import ReviewScope

_STRICT = ConfigDict(extra="forbid", frozen=True)


class CourseMove(StrEnum):
    SETTLE = "settle"
    REPEAT = "repeat"
    FURTHER = "further"


class Course(BaseModel):
    """One visit. Comments stay on ``ReviewAction``; labels stay on ``FunctionTag``."""

    model_config = _STRICT

    node_id: str
    grain: ReviewScope
    move: CourseMove


def input_digest(comments: Sequence[str], labels: Sequence[str]) -> str:
    """Hash of the input set. Not stored on the course row."""
    payload = {"comments": list(comments), "labels": list(labels)}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def decide_move(
    *,
    produced: bool,
    other_node_new: bool,
    grain: ReviewScope,
) -> CourseMove:
    """Same rule at every grain, including document.

    Settle when this visit added nothing new. Repeat when new information came
    from a different node_id. Further when this visit produced something the
    containing grain has not consumed; on the document that hands discoveries
    to the caller.
    """
    if not produced:
        return CourseMove.SETTLE
    if other_node_new:
        return CourseMove.REPEAT
    if grain is ReviewScope.DOCUMENT:
        return CourseMove.FURTHER
    return CourseMove.FURTHER


__all__ = ["Course", "CourseMove", "decide_move", "input_digest"]

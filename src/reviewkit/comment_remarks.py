"""Provider- and domain-blind presentation semantics for review comments."""

from __future__ import annotations
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from docxtor import PackageError, inventory_review_markup


class RemarkWeight(StrEnum):
    SERIOUS = "serious"
    COSMETIC = "cosmetic"
    UNKNOWN = "unknown"


class RemarkDisposition(StrEnum):
    APPLIED = "applied"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"
    ADVISORY = "advisory"


_SERIOUS = frozenset({"RISK", "CONFLICT", "HUMAN_DECISION", "CORRECTION"})
_COSMETIC = frozenset({"SUGGESTION", "QUESTION", "PRAISE", "SUMMARY", "COMMENT"})
_STATUS = re.compile(r"\bStatus:\s*([a-z_]+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ReviewRemark:
    comment_id: str
    text: str
    weight: RemarkWeight
    disposition: RemarkDisposition

    @property
    def stable_id(self) -> str:
        value = self.comment_id.strip()
        return value or "t-" + hashlib.sha256(self.text.encode()).hexdigest()[:12]


def remark_weight(text: str) -> RemarkWeight:
    match = re.match(r"^([A-Z_]+):", text.strip())
    if match is None:
        return RemarkWeight.UNKNOWN
    label = match.group(1)
    if label in _SERIOUS:
        return RemarkWeight.SERIOUS
    if label in _COSMETIC:
        return RemarkWeight.COSMETIC
    return RemarkWeight.UNKNOWN


def remark_disposition(text: str) -> RemarkDisposition:
    match = _STATUS.search(text)
    if match is None:
        return RemarkDisposition.ADVISORY
    status = match.group(1).casefold()
    if status == "applied":
        return RemarkDisposition.APPLIED
    if status == "not_applied":
        return RemarkDisposition.REJECTED
    if status in {"needs_human_decision", "conflict"}:
        return RemarkDisposition.UNRESOLVED
    return RemarkDisposition.ADVISORY


def review_remarks(source: str | Path | bytes) -> tuple[ReviewRemark, ...]:
    payload = source if isinstance(source, bytes) else Path(source).read_bytes()
    try:
        inventory = inventory_review_markup(payload)
    except (PackageError, OSError):
        return ()
    remarks = [
        ReviewRemark(
            item.comment_id, item.text, remark_weight(item.text), remark_disposition(item.text)
        )
        for item in inventory.comments
        if item.text.strip()
    ]
    return tuple(
        sorted(
            remarks,
            key=lambda item: (
                (0, f"{int(item.comment_id):010d}")
                if item.comment_id.isdigit()
                else (1, item.comment_id)
            ),
        )
    )


def compare_review_remarks(
    left: Sequence[ReviewRemark], right: Sequence[ReviewRemark]
) -> dict[str, object]:
    def key(item: ReviewRemark) -> str:
        return " ".join(item.text.split()).casefold()

    left_by_key = {key(item): item for item in left if key(item)}
    right_by_key = {key(item): item for item in right if key(item)}
    return {
        "shared": tuple(left_by_key[k] for k in left_by_key if k in right_by_key),
        "left_only": tuple(item for k, item in left_by_key.items() if k not in right_by_key),
        "right_only": tuple(item for k, item in right_by_key.items() if k not in left_by_key),
        "left_count": len(left),
        "right_count": len(right),
    }

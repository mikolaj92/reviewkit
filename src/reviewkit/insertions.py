"""Review-semantic paragraph insertion requests and suggestion marker grammar."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

InsertionKind = Literal["insert", "suggest"]
SUGGESTION_MARKER_PREFIX = "[SUGGESTION"


def format_suggestion_text(reason: str, text: str) -> str:
    return f"{SUGGESTION_MARKER_PREFIX}: {reason}]\n{text}"


def contains_suggestion_marker(text: str) -> bool:
    return SUGGESTION_MARKER_PREFIX in text


@dataclass(frozen=True)
class InsertionAction:
    action_id: str
    anchor: str
    text: str = ""
    kind: InsertionKind = "insert"
    reason: str = ""

    def rendered_text(self) -> str:
        return (
            format_suggestion_text(self.reason, self.text) if self.kind == "suggest" else self.text
        )

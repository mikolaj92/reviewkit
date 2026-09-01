"""Review anchor grammar; physical resolution belongs to Docxtor."""

from __future__ import annotations

ANCHOR_LAST = "body:p:last"


def _is_ascii_digits(token: str) -> bool:
    return token.isascii() and token.isdigit()


def parse_body_anchor_index(anchor: str) -> int | None:
    parts = anchor.split(":")
    if len(parts) == 3 and parts[:2] == ["body", "p"] and _is_ascii_digits(parts[2]):
        return int(parts[2])
    return None


def is_supported_anchor(anchor: str) -> bool:
    return anchor == ANCHOR_LAST or parse_body_anchor_index(anchor) is not None

"""The four levels of a DOCX walk, in order.

These names are the review vocabulary. Do not rename them grain, percent, or
sides.
"""

from __future__ import annotations

from enum import StrEnum


class Poziom(StrEnum):
    ZDANIE = "zdanie"
    AKAPIT = "akapit"
    ROZDZIAL = "rozdział"
    CALOSC = "całość"


WALK_ORDER = (Poziom.ZDANIE, Poziom.AKAPIT, Poziom.ROZDZIAL, Poziom.CALOSC)

__all__ = ["WALK_ORDER", "Poziom"]

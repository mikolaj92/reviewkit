"""The four levels of a one-DOCX review, in walk order.

These names are the review. Do not rename them grain, percent, or sides.
"""

from __future__ import annotations

from enum import StrEnum

from reviewkit.models import ReviewScope


class Poziom(StrEnum):
    """One cut of the document the stay-or-go loop walks."""

    ZDANIE = "zdanie"
    AKAPIT = "akapit"
    ROZDZIAL = "rozdział"
    CALOSC = "całość"


WALK_ORDER: tuple[Poziom, ...] = (
    Poziom.ZDANIE,
    Poziom.AKAPIT,
    Poziom.ROZDZIAL,
    Poziom.CALOSC,
)

_SCOPE = {
    Poziom.ZDANIE: ReviewScope.SENTENCE,
    Poziom.AKAPIT: ReviewScope.PARAGRAPH,
    Poziom.ROZDZIAL: ReviewScope.SECTION,
    Poziom.CALOSC: ReviewScope.DOCUMENT,
}


def scope_for(poziom: Poziom) -> ReviewScope:
    return _SCOPE[poziom]


__all__ = ["WALK_ORDER", "Poziom", "scope_for"]

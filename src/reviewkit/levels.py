"""Walk levels for one-DOCX review.

The names are zdanie, akapit, rozdział, całość. Do not substitute
grain / percent / sides.
"""

from __future__ import annotations

ZDANIE = "zdanie"
AKAPIT = "akapit"
ROZDZIAL = "rozdział"
CALOSC = "całość"

LEVEL_ORDER = (ZDANIE, AKAPIT, ROZDZIAL, CALOSC)

__all__ = ["AKAPIT", "CALOSC", "LEVEL_ORDER", "ROZDZIAL", "ZDANIE"]

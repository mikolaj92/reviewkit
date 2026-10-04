"""Walk levels for one-DOCX review.

The names are the review grains. Do not substitute grain / percent / sides.
"""

from __future__ import annotations

ZDANIE = "zdanie"
AKAPIT = "akapit"
ROZDZIAL = "rozdział"
CALOSC = "całość"

LEVEL_ORDER = (ZDANIE, AKAPIT, ROZDZIAL, CALOSC)

__all__ = ["AKAPIT", "CALOSC", "LEVEL_ORDER", "ROZDZIAL", "ZDANIE"]

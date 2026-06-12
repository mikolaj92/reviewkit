"""Public API for ReviewKit."""

from reviewkit.models import ReviewResult
from reviewkit.pipeline import review_document

__all__ = ["ReviewResult", "review_document"]

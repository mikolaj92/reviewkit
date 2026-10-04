"""Lock the public walk surface on the package root."""

from __future__ import annotations

import reviewkit

_WALK_SURFACE = (
    "AKAPIT",
    "CALOSC",
    "LEVEL_ORDER",
    "ROZDZIAL",
    "ZDANIE",
    "DocxReview",
    "DocxReviewer",
    "LiveDocx",
    "ReviewUnit",
    "StayOrGo",
    "WalkVisit",
    "review_docx",
    "walk_live_docx",
)


def test_walk_types_are_exported_from_package_root() -> None:
    for name in _WALK_SURFACE:
        assert name in reviewkit.__all__, name
        assert getattr(reviewkit, name) is not None


def test_removed_review_paths_are_not_on_the_package_root() -> None:
    for name in (
        "review_tree",
        "review_source",
        "review_document",
        "TaktReviewer",
        "Pack",
        "DecisionClient",
        "LLMClient",
        "detect",
        "judge",
        "parse_text",
        "TextDocumentParser",
        "DocumentParser",
        "DocxDocumentParser",
        "DocxFootnote",
        "read_footnotes",
    ):
        assert name not in reviewkit.__all__, name
        assert not hasattr(reviewkit, name)

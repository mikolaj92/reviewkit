"""Neutral purity assessment for final review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docxtor import docx_facts

from reviewkit.markup_purity import inspect_markup
from reviewkit.portable_trail import (
    PortableReviewTrailError,
    PortableReviewTrailProfile,
    has_portable_review_trail,
)

_REVIEW_ONLY_PREFIXES = ("word/comments", "word/people.xml")


@dataclass(frozen=True)
class ReviewArtifactPurityAssessment:
    revision_parts: tuple[str, ...] = ()
    suggestion_parts: tuple[str, ...] = ()
    has_comments: bool = False
    residual_review_parts: tuple[str, ...] = ()
    has_portable_trail: bool = False
    inspection_error: str | None = None

    @property
    def is_clean(self) -> bool:
        return not (
            self.revision_parts
            or self.suggestion_parts
            or self.has_comments
            or self.residual_review_parts
            or self.has_portable_trail
            or self.inspection_error
        )


def assess_review_artifact_purity(
    source: str | Path, *, trail_profile: PortableReviewTrailProfile
) -> ReviewArtifactPurityAssessment:
    """Inspect every neutral review residue and fail closed as typed data."""
    try:
        report = inspect_markup(source)
        facts = docx_facts(source)
        residual = tuple(
            sorted(part.name for part in facts.parts if part.name.startswith(_REVIEW_ONLY_PREFIXES))
        )
        trail = has_portable_review_trail(source, profile=trail_profile)
    except (OSError, ValueError, PortableReviewTrailError) as exc:
        return ReviewArtifactPurityAssessment(inspection_error=str(exc))
    return ReviewArtifactPurityAssessment(
        revision_parts=report.revision_parts,
        suggestion_parts=report.suggestion_parts,
        has_comments=report.has_comments,
        residual_review_parts=residual,
        has_portable_trail=trail,
    )

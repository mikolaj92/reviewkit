"""comparison models seams for DOCX provenance attribution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from reviewkit.models import ReviewAction


class ProvenanceStatus(StrEnum):
    VERIFIED_ACTION = "verified_action"
    VERIFIED_ACCEPTANCE = "verified_acceptance"
    SOURCE = "source"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReviewActionEvidence:
    """Prepared actions and byte hashes loaded from a trusted persisted sidecar."""

    source_sha256: str
    reviewed_sha256: str
    actions_sha256: str
    source_revision_signatures: tuple[str, ...]
    actions: tuple[ReviewAction, ...]


@dataclass(frozen=True)
class DocumentTransitionEvidence:
    """Verified byte hashes for one consumed-to-produced document transition."""

    input_sha256: str
    output_sha256: str


@dataclass(frozen=True)
class ProvenanceDiagnostic:
    code: str
    side: str | None = None
    part_name: str | None = None
    locator: str | None = None


@dataclass(frozen=True)
class ChangeProvenance:
    change_id: str
    event_type: str
    status: ProvenanceStatus
    action_ids: tuple[str, ...] = ()
    evidence_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComparisonProvenance:
    comparison_id: str
    left_sha256: str
    right_sha256: str
    coverage_diagnostics: tuple[ProvenanceDiagnostic, ...]
    changes: tuple[ChangeProvenance, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible report without copying document text."""
        return {
            "comparison_id": self.comparison_id,
            "left_sha256": self.left_sha256,
            "right_sha256": self.right_sha256,
            "coverage_diagnostics": [
                {
                    "code": item.code,
                    "side": item.side,
                    "part_name": item.part_name,
                    "locator": item.locator,
                }
                for item in self.coverage_diagnostics
            ],
            "changes": [
                {
                    "change_id": item.change_id,
                    "event_type": item.event_type,
                    "status": item.status.value,
                    "action_ids": list(item.action_ids),
                    "evidence_codes": list(item.evidence_codes),
                }
                for item in self.changes
            ],
        }

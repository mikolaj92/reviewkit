"""comparison seams for DOCX provenance attribution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from reviewkit.comparison_acceptance import _attribute_acceptance
from reviewkit.comparison_direct import _attribute_direct
from reviewkit.comparison_models import (
    ChangeProvenance,
    ComparisonProvenance,
    DocumentTransitionEvidence,
    ProvenanceStatus,
    ReviewActionEvidence,
)
from reviewkit.comparison_verification import (
    _diagnostics,
    _empty_rows,
    _map_direct_actions,
    _merge_diagnostics,
    _result,
    _targets,
    _verify_chain,
)

if TYPE_CHECKING:
    from docxtor import DocxDocumentComparison


def attribute_docx_changes(
    comparison: DocxDocumentComparison,
    *,
    action_source: str | Path,
    review_evidence: ReviewActionEvidence | None,
    transition_evidence: DocumentTransitionEvidence | None = None,
    source_to_reviewed: DocxDocumentComparison | None = None,
) -> ComparisonProvenance:
    """Attribute mechanically compared DOCX events to exact persisted actions.

    ``action_source`` is the immutable input DOCX used to prepare the actions.
    Hashes bind that source, the reviewed artifact, and (when present) one
    corrected-artifact transition. No metadata inside either DOCX is trusted.
    """
    diagnostics = _diagnostics(comparison)
    base_rows = _empty_rows(comparison)
    chain = _verify_chain(
        comparison,
        action_source=action_source,
        review_evidence=review_evidence,
        transition_evidence=transition_evidence,
        source_to_reviewed=source_to_reviewed,
    )
    if not chain.valid or chain.source_document is None or review_evidence is None:
        evidence_codes = chain.codes or ("review_evidence_missing",)
        rows = {
            key: ChangeProvenance(
                row.change_id,
                row.event_type,
                ProvenanceStatus.UNKNOWN,
                evidence_codes=evidence_codes,
            )
            for key, row in base_rows.items()
        }
        return _result(comparison, diagnostics, rows)

    if chain.pair_kind == "reviewed_to_corrected":
        assert source_to_reviewed is not None
        diagnostics = _merge_diagnostics(diagnostics, _diagnostics(source_to_reviewed))
        prior_targets = _targets(chain.source_document, review_evidence.actions)
        prior_mapped = _map_direct_actions(source_to_reviewed, prior_targets)
        prior = _attribute_direct(
            source_to_reviewed, prior_mapped, diagnostics=_diagnostics(source_to_reviewed)
        )
        rows = _attribute_acceptance(
            comparison,
            base_rows,
            prior,
            review_evidence.actions,
            diagnostics,
        )
    else:
        targets = _targets(chain.source_document, review_evidence.actions)
        mapped = _map_direct_actions(comparison, targets)
        rows = _attribute_direct(comparison, mapped, diagnostics=diagnostics).rows

    return _result(comparison, diagnostics, rows)

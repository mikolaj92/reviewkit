"""comparison acceptance seams for DOCX provenance attribution."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from reviewkit.comparison_direct import (
    _can_accept,
    _comment_identity,
    _DirectResult,
    _reference_key,
    _unique_comments,
)
from reviewkit.comparison_models import (
    ChangeProvenance,
    ProvenanceDiagnostic,
    ProvenanceStatus,
)
from reviewkit.comparison_verification import _blocked_by_diagnostic
from reviewkit.models import ReviewAction

if TYPE_CHECKING:
    from docxtor import DocxDocumentComparison


def _attribute_acceptance(
    comparison: DocxDocumentComparison,
    rows: dict[str, ChangeProvenance],
    prior: _DirectResult,
    actions: Sequence[ReviewAction],
    diagnostics: tuple[ProvenanceDiagnostic, ...],
) -> dict[str, ChangeProvenance]:
    action_by_id = {action.id: action for action in actions}
    prior_revision_to_action = prior.matched_revisions
    prior_comment_to_action = prior.matched_comments

    for event in comparison.revision_events:
        if (
            event.status.value != "resolved"
            or event.resolution_evidence is None
            or event.resolution_evidence.value != "accepted_text_equal"
            or event.left is None
        ):
            continue
        prior_candidates = [
            (prior_id, action_id)
            for prior_id, (action_id, reference) in prior_revision_to_action.items()
            if _reference_key(reference) == _reference_key(event.left)
        ]
        action_ids = {action_id for _prior_id, action_id in prior_candidates}
        if len(prior_candidates) != 1 or len(action_ids) != 1:
            continue
        action_id = next(iter(action_ids))
        action = action_by_id.get(action_id)
        if action is None or not _can_accept(action):
            continue
        if _blocked_by_diagnostic(
            diagnostics,
            event.left.container_id,
            "revision",
            pair_id=event.left.pair_id,
        ):
            continue
        rows[event.change_id] = ChangeProvenance(
            event.change_id,
            "revision",
            ProvenanceStatus.VERIFIED_ACCEPTANCE,
            (action_id,),
            ("reviewed_revision_matched", "accepted_text_equal", "transition_hashes_verified"),
        )

    source_review_comments = _unique_comments(prior.source_review_comments)
    for event in comparison.comment_changes:
        comment = event.left
        if comment is None:
            continue
        identity = _comment_identity(comment)
        source_matches = [
            item for item in source_review_comments if _comment_identity(item) == identity
        ]
        if len(source_matches) == 1:
            rows[event.change_id] = ChangeProvenance(
                event.change_id,
                "comment",
                ProvenanceStatus.SOURCE,
                evidence_codes=("source_comment_origin_carried_from_reviewed_artifact",),
            )
            continue
        if event.right is not None:
            continue
        action_matches = [
            (prior_id, action_id, item)
            for prior_id, action_id in prior_comment_to_action.items()
            for candidate_id, item in prior.action_review_comments
            if candidate_id == action_id
            and _comment_identity(item) == identity
            and prior_id in prior.rows
            and prior.rows[prior_id].status is ProvenanceStatus.VERIFIED_ACTION
        ]
        action_ids = {action_id for _prior_id, action_id, _item in action_matches}
        if len(action_matches) != 1 or len(action_ids) != 1:
            continue
        action_id = next(iter(action_ids))
        action = action_by_id.get(action_id)
        if action is None or not _can_accept(action):
            continue
        if _blocked_by_diagnostic(
            diagnostics,
            comment.anchor.locator if comment.anchor else None,
            "comment",
            pair_id=comment.anchor.pair_id if comment.anchor else None,
        ):
            continue
        rows[event.change_id] = ChangeProvenance(
            event.change_id,
            "comment",
            ProvenanceStatus.VERIFIED_ACCEPTANCE,
            (action_id,),
            ("reviewed_action_comment_matched", "transition_hashes_verified"),
        )

    return rows

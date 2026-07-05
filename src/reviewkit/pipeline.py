"""End-to-end review pipeline."""

from __future__ import annotations

from pathlib import Path

from reviewkit.actions import demote_cross_scope_overlaps, prepare_actions
from reviewkit.context import ReviewContextProvider
from reviewkit.document import ReviewDocument
from reviewkit.llm import LLMClient
from reviewkit.models import ReviewAction, ReviewFinding, ReviewResult, ReviewStats
from reviewkit.parser_docx import load_docx
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile, load_profile
from reviewkit.renderer_docx import render_corrected_docx, render_reviewed_docx
from reviewkit.reviewer import HierarchicalReviewer


def review_document(
    input_path: str | Path,
    profile_path: str | Path | ReviewProfile,
    llm: LLMClient,
    out_reviewed: str | Path = "reviewed.docx",
    out_corrected: str | Path = "corrected.docx",
    context_provider: ReviewContextProvider | None = None,
    action_policy: ActionPolicy | None = None,
    extra_actions: list[ReviewAction] | None = None,
) -> ReviewResult:
    """Run the hierarchical review and render the reviewed/corrected artifacts.

    ``extra_actions`` are pre-built actions from OUTSIDE the LLM (deterministic
    callers). Contract: pass them RAW (unprepared) - the pipeline runs them through
    the exact same machinery as reviewer-produced actions, so any pre-set ``status``
    is recomputed: validation against the document text (an ``original_text`` found
    nowhere in the node becomes CONFLICT regardless of the profile's ambiguity
    config - never a silent apply - while a non-unique match escalates per that
    config), the action policy, and the overlap guards against the LLM's actions
    (an overlapping cluster is demoted to CONFLICT as a whole, matched per action,
    so an extra reusing an LLM action's id is never collaterally demoted). Each
    action's ``source_system`` is preserved,
    prepared extras are appended after the reviewer's actions, and both artifacts
    include them: reviewed.docx as tracked edits/comments, corrected.docx applying
    only the APPLIED ones. With ``extra_actions=None`` or ``[]`` the result is
    identical to omitting the parameter.
    """
    # Accept an already-built profile as well as a folder path: callers that construct or cache
    # a ReviewProfile in memory shouldn't be forced to round-trip it through disk.
    profile = profile_path if isinstance(profile_path, ReviewProfile) else load_profile(profile_path)
    document = load_docx(input_path)
    reviewer = HierarchicalReviewer(
        profile=profile,
        llm=llm,
        context_provider=context_provider,
        action_policy=action_policy,
    )
    findings, actions, state = reviewer.review(document)

    if extra_actions:
        # Same machinery as reviewer output: prepare_actions validates each extra action
        # against the document and applies the action policy (plus the in-batch overlap
        # guard), then the cross-scope pass re-runs over the MERGED list so an extra edit
        # overlapping an LLM edit demotes exactly like two LLM edits would.
        prepared_extra = prepare_actions(document, profile, extra_actions, policy=action_policy)
        actions = demote_cross_scope_overlaps(document, actions + prepared_extra)

    reviewed_path: Path | None = None
    corrected_path: Path | None = None

    if profile.outputs.reviewed_docx:
        reviewed_path = render_reviewed_docx(document, actions, out_reviewed)
    if profile.outputs.corrected_docx:
        corrected_path = render_corrected_docx(document, actions, out_corrected)

    return ReviewResult(
        document=document,
        findings=findings,
        actions=actions,
        reviewed_docx=reviewed_path,
        corrected_docx=corrected_path,
        document_summary=state.document_summary,
        stats=ReviewStats.from_actions(actions),
        warnings=(
            _document_warnings(document)
            + _unresolved_finding_id_warnings(findings, actions)
            + state.warnings
        ),
        artifacts=_artifacts(reviewed_path=reviewed_path, corrected_path=corrected_path),
    )


def _document_warnings(document: ReviewDocument) -> list[str]:
    if document.metadata.get("tracked_revisions_detected") == "true":
        return ["Input DOCX contains tracked revisions."]
    return []


def _unresolved_finding_id_warnings(
    findings: list[ReviewFinding], actions: list[ReviewAction]
) -> list[str]:
    # The finding<->action linkage is the archetype's audit trail: it lets a consumer trace
    # an action back to the finding that motivated it. An action pointing at a finding_id that
    # no finding carries is a broken link (a hallucinated or stale reference), so surface it as
    # a warning rather than let the dangling reference pass silently.
    known = {finding.finding_id for finding in findings}
    # A finding whose duplicate was merged away carries the merged-away id(s) as aliases, so
    # an action that referenced the dropped copy still resolves and must not be flagged.
    for finding in findings:
        known.update(finding.metadata.get("merged_finding_ids", []))
    return [
        f"Action {action.id} references unknown finding_id {action.finding_id!r}."
        for action in actions
        if action.finding_id and action.finding_id not in known
    ]


def _artifacts(*, reviewed_path: Path | None, corrected_path: Path | None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if reviewed_path is not None:
        artifacts["reviewed_docx"] = str(reviewed_path)
    if corrected_path is not None:
        artifacts["corrected_docx"] = str(corrected_path)
    return artifacts

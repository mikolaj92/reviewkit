"""Format-neutral hierarchical review entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reviewkit.actions import demote_cross_scope_overlaps, prepare_actions
from reviewkit.context import ReviewContextProvider
from reviewkit.document import DocumentParser, ReviewDocument
from reviewkit.llm import LLMClient
from reviewkit.models import ReviewAction, ReviewFinding, ReviewResult, ReviewStats
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile, load_profile
from reviewkit.takt_reviewer import TaktReviewer


def review_tree(
    document: ReviewDocument,
    profile_path: str | Path | ReviewProfile,
    llm: LLMClient,
    context_provider: ReviewContextProvider | None = None,
    action_policy: ActionPolicy | None = None,
    extra_actions: list[ReviewAction] | None = None,
) -> ReviewResult:
    """Review an already parsed tree without reading or rendering any file format."""
    profile = (
        profile_path if isinstance(profile_path, ReviewProfile) else load_profile(profile_path)
    )
    reviewer = TaktReviewer(
        profile=profile,
        llm=llm,
        context_provider=context_provider,
        action_policy=action_policy,
    )
    findings, actions, state = reviewer.review(document)
    if extra_actions:
        prepared = prepare_actions(document, profile, extra_actions, policy=action_policy)
        actions = demote_cross_scope_overlaps(document, actions + prepared)
    return ReviewResult(
        document=document,
        findings=findings,
        actions=actions,
        document_summary=state.document_summary,
        stats=ReviewStats.from_actions(actions),
        warnings=(
            document_warnings(document)
            + unresolved_finding_id_warnings(findings, actions)
            + state.warnings
        ),
    )


def review_source(
    source: Any,
    parser: DocumentParser,
    profile_path: str | Path | ReviewProfile,
    llm: LLMClient,
    **kwargs: Any,
) -> ReviewResult:
    """Parse through an injected format adapter and review the resulting typed tree."""
    return review_tree(parser.parse(source), profile_path, llm, **kwargs)


def document_warnings(document: ReviewDocument) -> list[str]:
    if document.metadata.get("tracked_revisions_detected") == "true":
        return ["Input DOCX contains tracked revisions."]
    return []


def unresolved_finding_id_warnings(
    findings: list[ReviewFinding], actions: list[ReviewAction]
) -> list[str]:
    known = {finding.finding_id for finding in findings}
    for finding in findings:
        known.update(finding.metadata.get("merged_finding_ids", []))
    return [
        f"Action {action.id} references unknown finding_id {action.finding_id!r}."
        for action in actions
        if action.finding_id and action.finding_id not in known
    ]

"""Format-neutral hierarchical review entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reviewkit.actions import demote_cross_scope_overlaps, prepare_actions
from reviewkit.context import ReviewContextProvider
from reviewkit.decision import DecisionClient
from reviewkit.document import DocumentParser, ReviewDocument
from reviewkit.llm import LLMClient
from reviewkit.models import (
    ReviewAction,
    ReviewFinding,
    ReviewResult,
    ReviewScope,
    ReviewStats,
)
from reviewkit.pack import Pack
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile, load_profile
from reviewkit.takt_reviewer import ReviewPrior, TaktReviewer


def review_tree(
    document: ReviewDocument,
    profile_path: str | Path | ReviewProfile,
    llm: LLMClient,
    pack: Pack,
    decision: DecisionClient,
    context_provider: ReviewContextProvider | None = None,
    action_policy: ActionPolicy | None = None,
    extra_actions: list[ReviewAction] | None = None,
    *,
    prior: ReviewPrior = None,
    level: ReviewScope | str | None = None,
    passes: int = 1,
) -> ReviewResult:
    """Review an already parsed tree without reading or rendering any file format.

    Hosts pass typed ``Pack`` and ``DecisionClient`` instances. JSON files load
    through ``Pack.model_validate`` / ``Pack.model_validate_json`` only; this
    call site does not accept dict dumps. A review names, then judges, then
    optionally writes through ``LLMClient.complete_json``. There is no fused
    ``pack=None`` path.

    ``level`` selects one unit size (sentence, paragraph, section, or
    document). Call that same level again with ``prior`` to continue, or a
    different ``level`` when moving on. ``prior`` is a previous result; the
    later call returns those discoveries plus anything new. ``passes`` is an
    optional convenience loop over the same level. Default (no ``prior``, no
    ``level``, ``passes=1``) is today's single walk.
    """
    profile = (
        profile_path if isinstance(profile_path, ReviewProfile) else load_profile(profile_path)
    )
    reviewer = TaktReviewer(
        profile=profile,
        llm=llm,
        pack=pack,
        decision=decision,
        context_provider=context_provider,
        action_policy=action_policy,
    )
    findings, actions, state = reviewer.review(document, prior=prior, level=level, passes=passes)
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
        state=state,
    )


def review_source(
    source: Any,
    parser: DocumentParser,
    profile_path: str | Path | ReviewProfile,
    llm: LLMClient,
    pack: Pack,
    decision: DecisionClient,
    context_provider: ReviewContextProvider | None = None,
    action_policy: ActionPolicy | None = None,
    extra_actions: list[ReviewAction] | None = None,
    *,
    prior: ReviewPrior = None,
    level: ReviewScope | str | None = None,
    passes: int = 1,
) -> ReviewResult:
    """Parse through an injected format adapter and review the resulting typed tree."""
    return review_tree(
        parser.parse(source),
        profile_path,
        llm,
        pack,
        decision,
        context_provider=context_provider,
        action_policy=action_policy,
        extra_actions=extra_actions,
        prior=prior,
        level=level,
        passes=passes,
    )


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


__all__ = [
    "document_warnings",
    "review_source",
    "review_tree",
    "unresolved_finding_id_warnings",
]

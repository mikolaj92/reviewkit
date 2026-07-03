"""End-to-end review pipeline."""

from __future__ import annotations

from pathlib import Path

from reviewkit.context import ReviewContextProvider
from reviewkit.document import ReviewDocument
from reviewkit.llm import LLMClient
from reviewkit.models import ReviewResult, ReviewStats
from reviewkit.parser_docx import load_docx
from reviewkit.profile import load_profile
from reviewkit.renderer_docx import render_corrected_docx, render_reviewed_docx
from reviewkit.reviewer import HierarchicalReviewer


def review_document(
    input_path: str | Path,
    profile_path: str | Path,
    llm: LLMClient,
    out_reviewed: str | Path = "reviewed.docx",
    out_corrected: str | Path = "corrected.docx",
    context_provider: ReviewContextProvider | None = None,
) -> ReviewResult:
    profile = load_profile(profile_path)
    document = load_docx(input_path)
    reviewer = HierarchicalReviewer(profile=profile, llm=llm, context_provider=context_provider)
    findings, actions, state = reviewer.review(document)

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
        warnings=_document_warnings(document) + state.warnings,
        artifacts=_artifacts(reviewed_path=reviewed_path, corrected_path=corrected_path),
    )


def _document_warnings(document: ReviewDocument) -> list[str]:
    if document.metadata.get("tracked_revisions_detected") == "true":
        return ["Input DOCX contains tracked revisions."]
    return []


def _artifacts(*, reviewed_path: Path | None, corrected_path: Path | None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if reviewed_path is not None:
        artifacts["reviewed_docx"] = str(reviewed_path)
    if corrected_path is not None:
        artifacts["corrected_docx"] = str(corrected_path)
    return artifacts

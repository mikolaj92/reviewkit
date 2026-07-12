"""Takt-specific smoke tests for the ReviewKit + takt 0.1.1 integration.

These tests exercise the plant, cascade, and TaktReviewer path.
They are intentionally small and do not duplicate all old hierarchical tests.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument
import pytest

from reviewkit import review_document
from reviewkit.llm import MockLLMClient
from reviewkit.plant import ReviewDocumentPlant
from reviewkit.takt_reviewer import TaktReviewer


def _make_docx(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "in.docx"
    d = DocxDocument()
    d.add_paragraph(text)
    d.save(p)
    return p


def test_review_document_plant_builds_correct_tree(tmp_path: Path) -> None:
    docx = _make_docx(tmp_path, "First sentence. Second sentence.\n\nAnother paragraph.")
    # We go through the public loader to get a real ReviewDocument
    from reviewkit.parser_docx import load_docx

    doc = load_docx(docx)
    plant = ReviewDocumentPlant(doc)

    nodes = list(plant.sequential_scan())
    # We expect sentences first (post-order), then paragraphs, sections, document
    ids = [n.id for n in nodes]
    assert any("sentence" in i or i for i in ids)  # at least some nodes
    assert len(nodes) >= 4  # document + section + paragraph + at least one sentence


def test_takt_reviewer_basic_run(tmp_path: Path) -> None:
    """End-to-end through TaktReviewer (the new core)."""
    docx = _make_docx(tmp_path, "Ala ma kota.")

    llm = MockLLMClient(
        responses=[
            {"actions": [], "summary": "ok"},
            {"actions": [], "summary": "ok"},
            {"actions": [], "summary": "ok"},
            {"actions": [], "summary": "Dokument ok."},
        ]
    )
    from reviewkit.profile import load_profile

    profile = load_profile("examples/profiles/story.teacher")
    reviewer = TaktReviewer(
        profile=profile,
        llm=llm,
    )
    from reviewkit.parser_docx import load_docx

    document = load_docx(docx)
    findings, actions, state = reviewer.review(document)

    assert isinstance(findings, list)
    assert isinstance(actions, list)

def test_public_api_still_works_with_takt(tmp_path: Path) -> None:
    """The main user entrypoint must continue to work after the total migration."""
    docx = _make_docx(tmp_path, "Test input for full pipeline.")

    llm = MockLLMClient(
        responses=[
            {"actions": [], "summary": "s"},
            {"actions": [], "summary": "p"},
            {"actions": [], "summary": "sec"},
            {"actions": [], "summary": "doc"},
        ]
    )

    result = review_document(
        input_path=docx,
        profile_path="examples/profiles/story.teacher",
        llm=llm,
        out_reviewed=tmp_path / "r.docx",
        out_corrected=tmp_path / "c.docx",
    )

    assert result.reviewed_docx is not None or result.corrected_docx is not None
    assert isinstance(result.actions, list)
    assert isinstance(result.findings, list)

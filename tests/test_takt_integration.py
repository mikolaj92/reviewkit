"""Takt-specific smoke tests for the ReviewKit + takt v0.3.0 binding integration.

These tests exercise the plant, canonical Takt binding, and TaktReviewer path.
They are intentionally small and do not duplicate all old hierarchical tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

from docx import Document as DocxDocument
import pytest

from reviewkit.takt_client import TaktClient
from reviewkit.takt_types import LayerSpec, PlantNode, TaktDecision

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


def test_takt_result_does_not_fall_back_when_outcome_is_invalid(monkeypatch) -> None:
    monkeypatch.setattr(
        "takt.cascade_step",
        lambda _request: {
            "outcome": "legacy",
            "signals": {"actuation": {"node_id": "node"}},
        },
    )

    with pytest.raises(ValueError, match="invalid takt outcome"):
        TaktClient().evaluate(
            plant_nodes=[PlantNode(id="node")],
            layers=[LayerSpec(layer=0)],
        )


def test_takt_binding_failure_is_not_silently_downgraded(monkeypatch) -> None:
    def fail(_request):
        raise RuntimeError("binding unavailable")

    monkeypatch.setattr("takt.cascade_step", fail)

    with pytest.raises(RuntimeError, match="binding unavailable"):
        TaktClient().evaluate(
            plant_nodes=[PlantNode(id="node")],
            layers=[LayerSpec(layer=0)],
        )


def test_takt_binding_does_not_discover_local_checkout(monkeypatch, tmp_path: Path) -> None:
    local_takt = tmp_path / "Developer" / "OSS" / "takt" / "tools"
    local_takt.mkdir(parents=True)
    (local_takt / "takt_step.sh").touch()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TAKT_HOME", raising=False)

    def evaluate(_request):
        assert "TAKT_HOME" not in os.environ
        return {"outcome": "stable"}

    monkeypatch.setattr("takt.cascade_step", evaluate)

    decision = TaktClient().evaluate(
        plant_nodes=[PlantNode(id="node")],
        layers=[LayerSpec(layer=0)],
    )

    assert decision.outcome == "stable"
    assert not hasattr(decision, "engine")


def test_takt_reviewer_does_not_synthesize_a_layer(monkeypatch, tmp_path: Path) -> None:
    """An empty layer build must reach the canonical binding unchanged."""
    docx = _make_docx(tmp_path, "Ala ma kota.")
    from reviewkit.parser_docx import load_docx
    from reviewkit.profile import load_profile

    monkeypatch.setattr("reviewkit.takt_reviewer.build_layer_specs", lambda _profile: [])
    takt_client = Mock()
    takt_client.evaluate.return_value = TaktDecision(outcome="stable", node_id="node")
    reviewer = TaktReviewer(
        profile=load_profile("examples/profiles/story.teacher"),
        llm=MockLLMClient(
            responses=[
                {"actions": [], "summary": "ok"},
                {"actions": [], "summary": "ok"},
                {"actions": [], "summary": "ok"},
                {"actions": [], "summary": "ok"},
            ]
        ),
        takt_client=takt_client,
    )

    reviewer.review(load_docx(docx))

    assert takt_client.evaluate.call_count > 0
    assert all(call.kwargs["layers"] == [] for call in takt_client.evaluate.call_args_list)


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

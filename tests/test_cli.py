"""CLI behaviour: pluggable LLM client and JSON report emission."""

from __future__ import annotations

import importlib.metadata as metadata
import json
import re
import tomllib
from pathlib import Path

import pytest
import typer
from docx import Document as DocxDocument
from typer.testing import CliRunner

from reviewkit.cli import _resolve_llm, app
from reviewkit.llm import MockLLMClient

runner = CliRunner()


def _make_docx(tmp_path: Path) -> Path:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("The quick brown fox.")
    docx.save(input_path)
    return input_path


def test_cli_writes_json_report_when_out_report_given(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path)
    report_path = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            str(input_path),
            "--profile",
            "examples/profiles/story.teacher",
            "--out-reviewed",
            str(tmp_path / "reviewed.docx"),
            "--out-corrected",
            str(tmp_path / "corrected.docx"),
            "--out-report",
            str(report_path),
            "--llm",
            "reviewkit.llm:MockLLMClient",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "JSON report:" in result.output
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    # The JSON report is a first-class deliverable, so it must carry the rollups.
    assert "actions_by_status" in payload
    assert "findings_by_severity" in payload


def test_cli_skips_json_report_by_default(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path)
    result = runner.invoke(
        app,
        [
            str(input_path),
            "--profile",
            "examples/profiles/story.teacher",
            "--out-reviewed",
            str(tmp_path / "reviewed.docx"),
            "--out-corrected",
            str(tmp_path / "corrected.docx"),
            "--llm",
            "reviewkit.llm:MockLLMClient",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "JSON report:" not in result.output


def test_cli_rejects_missing_llm_configuration(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path)
    result = runner.invoke(
        app,
        [str(input_path), "--profile", "examples/profiles/story.teacher"],
    )

    assert result.exit_code != 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--llm is required" in plain


def test_cli_accepts_injected_llm_factory(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path)
    result = runner.invoke(
        app,
        [
            str(input_path),
            "--profile",
            "examples/profiles/story.teacher",
            "--out-reviewed",
            str(tmp_path / "reviewed.docx"),
            "--out-corrected",
            str(tmp_path / "corrected.docx"),
            "--llm",
            "reviewkit.llm:MockLLMClient",
        ],
    )

    assert result.exit_code == 0, result.output


def test_resolve_llm_requires_explicit_client() -> None:
    with pytest.raises(typer.BadParameter, match="--llm is required"):
        _resolve_llm(None)


def test_resolve_llm_imports_dotted_factory() -> None:
    assert isinstance(_resolve_llm("reviewkit.llm:MockLLMClient"), MockLLMClient)


def test_resolve_llm_rejects_spec_without_colon() -> None:
    with pytest.raises(typer.BadParameter):
        _resolve_llm("reviewkit.llm.MockLLMClient")


def test_resolve_llm_rejects_unimportable_module() -> None:
    with pytest.raises(typer.BadParameter):
        _resolve_llm("reviewkit.does_not_exist:make_client")


def test_resolve_llm_rejects_missing_attribute() -> None:
    with pytest.raises(typer.BadParameter):
        _resolve_llm("reviewkit.llm:NoSuchFactory")


def test_resolve_llm_rejects_factory_returning_wrong_type() -> None:
    with pytest.raises(typer.BadParameter, match="did not return an LLMClient"):
        _resolve_llm("builtins:dict")


def test_console_scripts_expose_only_reviewkit_cli() -> None:
    """Do not advertise reviewkit-effector until reviewkit.effector exists."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = pyproject["project"]["scripts"]
    assert scripts == {"reviewkit": "reviewkit.cli:app"}

    installed = [
        ep.name
        for ep in metadata.entry_points(group="console_scripts")
        if ep.name.startswith("reviewkit")
    ]
    assert installed == ["reviewkit"]


def test_dev_tools_live_only_in_dependency_groups() -> None:
    """mypy/pytest/ruff pins live in one place: [dependency-groups] dev."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert "optional-dependencies" not in pyproject.get("project", {})
    assert pyproject["dependency-groups"]["dev"] == [
        "mypy>=2.1.1",
        "pytest>=9.1.1",
        "ruff>=0.16.5",
    ]
    contributing = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "uv sync --group dev" in contributing

"""CLI walks one DOCX in place."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument
from typer.testing import CliRunner

from reviewkit.cli import app
from reviewkit.live_docx import LiveDocx
from reviewkit.walk import ReviewUnit, StayOrGo

runner = CliRunner()


class AlwaysGo:
    def decide(self, unit: ReviewUnit, docx: LiveDocx) -> StayOrGo:
        return StayOrGo.GO


def make_reviewer() -> AlwaysGo:
    return AlwaysGo()


def test_cli_walks_the_same_docx(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("The quick brown fox.")
    docx.save(input_path)

    result = runner.invoke(
        app,
        [str(input_path), "--reviewer", "test_cli:make_reviewer"],
    )

    assert result.exit_code == 0, result.output
    assert str(input_path) in result.output
    assert "Visits:" in result.output

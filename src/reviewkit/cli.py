"""Command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reviewkit.llm import MockLLMClient
from reviewkit.pipeline import review_document

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def review(
    input_docx: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    profile: Annotated[
        Path,
        typer.Option("--profile", exists=True, file_okay=False, dir_okay=True, readable=True),
    ],
    out_reviewed: Annotated[Path, typer.Option("--out-reviewed")] = Path("reviewed.docx"),
    out_corrected: Annotated[Path, typer.Option("--out-corrected")] = Path("corrected.docx"),
) -> None:
    result = review_document(
        input_path=input_docx,
        profile_path=profile,
        llm=MockLLMClient(),
        out_reviewed=out_reviewed,
        out_corrected=out_corrected,
    )
    console.print(f"Reviewed DOCX: {result.reviewed_docx}")
    console.print(f"Corrected DOCX: {result.corrected_docx}")
    console.print(f"Actions: {len(result.actions)}")
    console.print(f"Applied: {result.stats.applied_count}")
    console.print(f"Conflicts: {result.stats.conflict_count}")

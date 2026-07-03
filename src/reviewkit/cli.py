"""Command line interface."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from reviewkit.llm import LLMClient, MockLLMClient
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
    out_report: Annotated[Path | None, typer.Option("--out-report")] = None,
    llm: Annotated[
        str | None,
        typer.Option(
            "--llm",
            help=(
                "Dotted 'module:factory' path to a zero-arg callable returning an LLMClient. "
                "Defaults to the built-in MockLLMClient."
            ),
        ),
    ] = None,
) -> None:
    client = _resolve_llm(llm)
    result = review_document(
        input_path=input_docx,
        profile_path=profile,
        llm=client,
        out_reviewed=out_reviewed,
        out_corrected=out_corrected,
    )
    console.print(f"Reviewed DOCX: {result.reviewed_docx}")
    console.print(f"Corrected DOCX: {result.corrected_docx}")
    if out_report is not None:
        report_path = result.save_json(out_report)
        console.print(f"JSON report: {report_path}")
    console.print(f"Actions: {len(result.actions)}")
    console.print(f"Applied: {result.stats.applied_count}")
    console.print(f"Conflicts: {result.stats.conflict_count}")


def _resolve_llm(spec: str | None) -> LLMClient:
    if spec is None:
        return MockLLMClient()
    if ":" not in spec:
        msg = f"--llm must be 'module:factory' (a colon-separated path), got {spec!r}."
        raise typer.BadParameter(msg)
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise typer.BadParameter(f"--llm module {module_name!r} could not be imported: {error}")
    try:
        factory = getattr(module, attr)
    except AttributeError:
        raise typer.BadParameter(f"--llm factory {attr!r} not found in module {module_name!r}.")
    if not callable(factory):
        raise typer.BadParameter(f"--llm target {spec!r} is not callable.")
    return factory()

"""Command line interface: walk one DOCX in place."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from reviewkit.review_docx import review_docx

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def review(
    input_docx: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    reviewer: Annotated[
        str,
        typer.Option(
            "--reviewer",
            help="Dotted 'module:factory' path to a zero-arg callable returning a DocxReviewer.",
        ),
    ],
) -> None:
    client = _resolve_reviewer(reviewer)
    result = review_docx(input_docx, client)
    console.print(f"Reviewed DOCX: {result.path}")
    console.print(f"Visits: {len(result.visits)}")


def _resolve_reviewer(spec: str) -> Any:
    if ":" not in spec:
        raise typer.BadParameter(
            f"--reviewer must be 'module:factory' (a colon-separated path), got {spec!r}."
        )
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise typer.BadParameter(
            f"--reviewer module {module_name!r} could not be imported: {error}"
        ) from error
    try:
        factory = getattr(module, attr)
    except AttributeError as error:
        raise typer.BadParameter(
            f"--reviewer factory {attr!r} not found in module {module_name!r}."
        ) from error
    if not callable(factory):
        raise typer.BadParameter(f"--reviewer target {spec!r} is not callable.")
    client = factory()
    if not callable(getattr(client, "decide", client)):
        raise typer.BadParameter(
            f"--reviewer factory {spec!r} did not return a DocxReviewer with decide()."
        )
    return client

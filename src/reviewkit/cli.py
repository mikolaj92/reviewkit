"""Command line interface."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from reviewkit.decision import DecisionClient
from reviewkit.llm import LLMClient
from reviewkit.pack import Pack
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
    pack: Annotated[
        Path,
        typer.Option(
            "--pack",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Required Pack JSON (ontology, units, rules).",
        ),
    ],
    decision: Annotated[
        str,
        typer.Option(
            "--decision",
            help=(
                "Required dotted 'module:factory' path to a zero-arg callable returning "
                "a DecisionClient."
            ),
        ),
    ],
    llm: Annotated[
        str,
        typer.Option(
            "--llm",
            help=(
                "Required dotted 'module:factory' path to a zero-arg callable returning "
                "an LLMClient."
            ),
        ),
    ],
    out_reviewed: Annotated[Path, typer.Option("--out-reviewed")] = Path("reviewed.docx"),
    out_corrected: Annotated[Path, typer.Option("--out-corrected")] = Path("corrected.docx"),
    out_report: Annotated[Path | None, typer.Option("--out-report")] = None,
) -> None:
    client = _resolve_llm(llm)
    decision_client = _resolve_decision(decision)
    result = review_document(
        input_path=input_docx,
        profile_path=profile,
        llm=client,
        pack=_load_pack(pack),
        decision=decision_client,
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


def _load_pack(path: Path) -> Pack:
    return Pack.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_llm(spec: str | None) -> LLMClient:
    client = _resolve_factory(spec, flag="--llm", missing="no default LLM client is configured.")
    if not callable(getattr(client, "complete_json", None)):
        raise typer.BadParameter(
            f"--llm factory {spec!r} did not return an LLMClient with complete_json()."
        )
    return client


def _resolve_decision(spec: str | None) -> DecisionClient:
    client = _resolve_factory(
        spec, flag="--decision", missing="no default DecisionClient is configured."
    )
    if not callable(getattr(client, "decide", None)):
        raise typer.BadParameter(
            f"--decision factory {spec!r} did not return a DecisionClient with decide()."
        )
    return client


def _resolve_factory(spec: str | None, *, flag: str, missing: str) -> Any:
    if spec is None:
        raise typer.BadParameter(f"{flag} is required; {missing}")
    if ":" not in spec:
        msg = f"{flag} must be 'module:factory' (a colon-separated path), got {spec!r}."
        raise typer.BadParameter(msg)
    module_name, _, attr = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise typer.BadParameter(f"{flag} module {module_name!r} could not be imported: {error}")
    try:
        factory = getattr(module, attr)
    except AttributeError:
        raise typer.BadParameter(f"{flag} factory {attr!r} not found in module {module_name!r}.")
    if not callable(factory):
        raise typer.BadParameter(f"{flag} target {spec!r} is not callable.")
    return factory()

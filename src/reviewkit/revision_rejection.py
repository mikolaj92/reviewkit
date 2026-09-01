"""Reject all tracked revisions through Docxtor's neutral byte API."""

from __future__ import annotations

from pathlib import Path

from docxtor import (
    PackageError,
    PublishError,
    RejectRevisionsError as DocxtorRejectRevisionsError,
    publish_docx,
    reject_all_revisions_bytes,
)

from reviewkit.markup_purity import inspect_markup


class RejectRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be rejected losslessly."""


def reject_all_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool = True,
) -> Path:
    """Reject every change and atomically publish the resulting physical DOCX."""
    source = Path(reviewed_path)
    destination = Path(out_path)

    def validate(path: Path) -> None:
        report = inspect_markup(path)
        if report.has_tracked_revisions or (drop_comments and report.has_comments):
            raise RejectRevisionsError(
                f"reject_all_revisions left markup in {destination}: "
                f"revision parts={report.revision_parts}, comments={report.comment_count}"
            )

    try:
        receipt = reject_all_revisions_bytes(source.read_bytes(), drop_comments=drop_comments)
        publish_docx(receipt.output_bytes, destination, validators=(validate,))
    except RejectRevisionsError:
        raise
    except (
        OSError,
        DocxtorRejectRevisionsError,
        PackageError,
        PublishError,
        ValueError,
    ) as exc:
        raise RejectRevisionsError(str(exc)) from exc
    return destination

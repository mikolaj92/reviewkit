"""Accept all tracked revisions through Docxtor's neutral byte API."""

from __future__ import annotations

from pathlib import Path

from reviewkit.revision_package import RevisionPackageError
from docxtor import (
    AcceptRevisionsError as DocxtorAcceptRevisionsError,
    PackageError,
    PublishError,
    accept_all_revisions_bytes,
    publish_docx,
)

from reviewkit.markup_purity import inspect_markup
from reviewkit.revision_rejection import RejectRevisionsError, reject_all_revisions

__all__ = [
    "AcceptRevisionsError",
    "RejectRevisionsError",
    "accept_all_revisions",
    "apply_reviewed_markup",
    "reject_all_revisions",
]


class AcceptRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be accepted losslessly."""


def accept_all_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool = True,
) -> Path:
    """Accept every change and atomically publish the resulting physical DOCX."""
    source = Path(reviewed_path)
    destination = Path(out_path)

    def validate(path: Path) -> None:
        report = inspect_markup(path)
        if report.has_tracked_revisions or (drop_comments and report.has_comments):
            raise AcceptRevisionsError(
                f"accept_all_revisions left markup in {destination}: "
                f"revision parts={report.revision_parts}, comments={report.comment_count}"
            )

    try:
        receipt = accept_all_revisions_bytes(source.read_bytes(), drop_comments=drop_comments)
        publish_docx(receipt.output_bytes, destination, validators=(validate,))
    except AcceptRevisionsError:
        raise
    except (
        OSError,
        DocxtorAcceptRevisionsError,
        PackageError,
        PublishError,
        RevisionPackageError,
        ValueError,
    ) as exc:
        raise AcceptRevisionsError(str(exc)) from exc
    return destination


apply_reviewed_markup = accept_all_revisions

"""Review markup purity projected exclusively from typed Docxtor inventory."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from docxtor import PackageError, inventory_docx, inventory_review_markup
from reviewkit.insertions import SUGGESTION_MARKER_PREFIX


@dataclass(frozen=True)
class MarkupReport:
    revision_parts: tuple[str, ...] = ()
    revision_kinds: tuple[str, ...] = ()
    comment_count: int = 0
    suggestion_parts: tuple[str, ...] = ()

    @property
    def has_tracked_revisions(self) -> bool:
        return bool(self.revision_parts)

    @property
    def has_comments(self) -> bool:
        return self.comment_count > 0

    @property
    def has_suggestion_marker(self) -> bool:
        return bool(self.suggestion_parts)

    @property
    def is_clean(self) -> bool:
        return not (self.has_tracked_revisions or self.has_comments or self.has_suggestion_marker)


def inspect_markup(path: str | Path) -> MarkupReport:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    data = source.read_bytes()
    inventory = inventory_review_markup(data)
    fatal = [
        diagnostic.message
        for diagnostic in inventory.diagnostics
        if diagnostic.code in {"package_unreadable", "comments_unreadable"}
    ]
    if fatal:
        raise PackageError("; ".join(fatal))
    package = inventory_docx(data)
    marker = SUGGESTION_MARKER_PREFIX
    suggestions = tuple(
        sorted({surface.part_name for surface in package.surfaces if marker in surface.value})
    )
    unsupported = [
        d
        for d in inventory.diagnostics
        if d.code in {"unsupported_revision", "unsupported_namespace"}
    ]
    revision_parts = tuple(
        sorted(
            {revision.part_name for revision in inventory.revisions}
            | {d.part_name for d in unsupported if d.part_name}
        )
    )
    revision_kinds = tuple(
        sorted(
            {revision.raw_kind for revision in inventory.revisions}
            | {d.message.split()[0] for d in unsupported}
        )
    )
    return MarkupReport(revision_parts, revision_kinds, len(inventory.comments), suggestions)


def has_tracked_revisions(path: str | Path) -> bool:
    return inspect_markup(path).has_tracked_revisions


def has_comments(path: str | Path) -> bool:
    return inspect_markup(path).has_comments


def has_suggestion_marker(path: str | Path) -> bool:
    return inspect_markup(path).has_suggestion_marker

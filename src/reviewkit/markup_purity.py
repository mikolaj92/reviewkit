"""Public markup-purity / tracked-change inspection API.

reviewkit owns the OOXML tracked-change and comment markup grammar: it renders
reviewed DOCX with real Word tracked changes and comments. This module is the
single public place to ask "is this ``.docx`` clean?" so consumers never
re-implement that grammar. Detection of the markup lives here; the *policy*
(whether a given document is allowed to carry markup, and what to do about it)
stays with the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from reviewkit.insertions import SUGGESTION_MARKER_PREFIX
from reviewkit.revision_package import parse_xml, read_package_entries, revision_kinds

_CONTENT_PART_PREFIX = "word/"
_CONTENT_PART_SUFFIX = ".xml"

_COMMENTS_PART = "word/comments.xml"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# The literal ``[SUGGESTION`` text marker reviewkit's own ``suggest`` insertions
# emit (see :mod:`reviewkit.insertions`). It is written verbatim as run text, so
# a byte scan over the same ``word/*.xml`` parts as the revision grammar finds
# every surviving marker, wherever it landed.
_SUGGESTION_MARKER_BYTES = SUGGESTION_MARKER_PREFIX.encode("ascii")
_DOCUMENT_PART = "word/document.xml"


@dataclass(frozen=True)
class MarkupReport:
    """Structured result of inspecting a ``.docx`` package for review markup.

    ``revision_parts`` are the package part names carrying tracked-change / move
    / format / table revision markup; ``revision_kinds`` are the distinct OOXML
    element local-names found (``ins``, ``del``, ``moveFrom``, ...);
    ``comment_count`` is the number of populated ``w:comment`` elements;
    ``suggestion_parts`` are the part names carrying the literal ``[SUGGESTION``
    text marker. Every field is empty / zero for a clean document.
    """

    revision_parts: tuple[str, ...] = ()
    revision_kinds: tuple[str, ...] = ()
    comment_count: int = 0
    suggestion_parts: tuple[str, ...] = ()

    @property
    def has_tracked_revisions(self) -> bool:
        """True when any tracked-change/move/format/table revision markup is present."""
        return bool(self.revision_parts)

    @property
    def has_comments(self) -> bool:
        """True when the package carries at least one populated comment."""
        return self.comment_count > 0

    @property
    def has_suggestion_marker(self) -> bool:
        """True when any part carries the literal ``[SUGGESTION`` text marker."""
        return bool(self.suggestion_parts)

    @property
    def is_clean(self) -> bool:
        """True when the package carries no revision markup, no suggestion markers and no comments."""
        return not self.revision_parts and not self.suggestion_parts and self.comment_count == 0


def inspect_markup(path: str | Path) -> MarkupReport:
    """Inspect a ``.docx`` package for revisions, comments and suggestion markers.

    Returns a :class:`MarkupReport` covering tracked/move/format/table revisions,
    populated comments and the literal ``[SUGGESTION`` text markers reviewkit's
    ``suggest`` insertions emit. A zip that lacks ``word/document.xml`` is not a
    DOCX package at all and raises ``zipfile.BadZipFile`` instead of scanning
    nothing and reporting clean. Propagates the underlying ``OSError`` /
    ``zipfile.BadZipFile`` if ``path`` cannot be opened as a ``.docx`` package --
    an un-inspectable file is never silently reported as clean; the caller's
    policy decides how to treat that.
    """
    revision_parts: list[str] = []
    found_revision_kinds: set[str] = set()
    suggestion_parts: list[str] = []
    comment_count = 0
    entries = read_package_entries(Path(path))
    names = {info.filename for info, _data in entries}
    if _DOCUMENT_PART not in names:
        raise BadZipFile(f"not a DOCX package: missing {_DOCUMENT_PART} in {path}")
    for info, data in entries:
        name = info.filename
        if not (name.startswith(_CONTENT_PART_PREFIX) and name.endswith(_CONTENT_PART_SUFFIX)):
            continue
        root = parse_xml(data)
        found = revision_kinds(root, _W)
        if found:
            revision_parts.append(name)
            found_revision_kinds.update(found)
        if _SUGGESTION_MARKER_BYTES in data:
            suggestion_parts.append(name)
        if name == _COMMENTS_PART:
            comment_count = sum(1 for _element in root.iter(f"{{{_W}}}comment"))
    return MarkupReport(
        revision_parts=tuple(sorted(revision_parts)),
        revision_kinds=tuple(sorted(found_revision_kinds)),
        comment_count=comment_count,
        suggestion_parts=tuple(sorted(suggestion_parts)),
    )


def has_tracked_revisions(path: str | Path) -> bool:
    """True when the ``.docx`` at ``path`` carries any tracked/move/format/table revision."""
    return inspect_markup(path).has_tracked_revisions


def has_comments(path: str | Path) -> bool:
    """True when the ``.docx`` at ``path`` carries any populated comment."""
    return inspect_markup(path).has_comments


def has_suggestion_marker(path: str | Path) -> bool:
    """True when any part of the ``.docx`` at ``path`` carries the ``[SUGGESTION`` text marker."""
    return inspect_markup(path).has_suggestion_marker

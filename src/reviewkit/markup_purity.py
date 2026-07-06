"""Public markup-purity / tracked-change inspection API.

reviewkit owns the OOXML tracked-change and comment markup grammar: it renders
reviewed DOCX with real Word tracked changes and comments. This module is the
single public place to ask "is this ``.docx`` clean?" so consumers never
re-implement that grammar. Detection of the markup lives here; the *policy*
(whether a given document is allowed to carry markup, and what to do about it)
stays with the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

# Full tracked-change / move / format / table-structure revision grammar Word can
# emit under Track Changes (ISO/IEC 29500 §17.13): edits (w:ins/w:del), moves
# (w:moveFrom/w:moveTo), the property-change wrappers (w:*PrChange), the table
# revision marks (w:cellIns/w:cellDel/w:cellMerge/w:tblGridChange/w:tblPrExChange)
# and legacy numbering changes. The trailing lookahead pins each element name to a
# delimiter so lookalikes never match: <w:insideH>/<w:insideV> (table borders) are
# not <w:ins>, <w:tblPrEx> (table property exceptions) is not <w:tblPrExChange>,
# and the ubiquitous <w:sectPr>/<w:pPr>/<w:rPr>/<w:tcPr>/<w:trPr>/<w:tblPr>
# property wrappers are not their *Change revisions -- so a clean document, which
# is full of those wrappers, never trips the detector.
#
# The ``w:`` prefix is hard-coded: every mainstream producer (Word, python-docx,
# LibreOffice, Google Docs export, the Open XML SDK) binds the WordprocessingML
# namespace to ``w:`` in the parts scanned here, so pinning the prefix keeps the
# grammar simple without missing real-world markup. A byte scan cannot resolve
# namespace URIs anyway, and matching an arbitrary ``<*:ins>`` prefix would risk
# false positives from unrelated namespaces that reuse these local names.
_REVISION_TAG_RE = re.compile(
    rb"<w:(ins|del|moveFrom|moveTo|rPrChange|pPrChange|sectPrChange|"
    rb"tblPrChange|trPrChange|tcPrChange|cellIns|cellDel|cellMerge|"
    rb"tblGridChange|tblPrExChange|numberingChange)(?=[\s>/])"
)

# Every revision element above appears ONLY in revised content, so there is no
# need for a part allowlist: scan each ``.xml`` part under ``word/`` and revisions
# living in a header, footer, footnote, endnote or the glossary document surface
# too. The grammar cannot false-positive on the ``w:trackChanges`` *setting* in
# settings.xml, nor on the ``w:*Pr`` property wrappers in styles.xml.
_CONTENT_PART_PREFIX = "word/"
_CONTENT_PART_SUFFIX = ".xml"

# A populated comment element in word/comments.xml. The lookahead keeps
# <w:commentReference>/<w:commentRangeStart>/<w:commentRangeEnd> (which live in
# document.xml, not the comments part) from ever being counted as comments.
_COMMENT_TAG_RE = re.compile(rb"<w:comment(?=[\s>/])")
_COMMENTS_PART = "word/comments.xml"


@dataclass(frozen=True)
class MarkupReport:
    """Structured result of inspecting a ``.docx`` package for review markup.

    ``revision_parts`` are the package part names carrying tracked-change / move
    / format / table revision markup; ``revision_kinds`` are the distinct OOXML
    element local-names found (``ins``, ``del``, ``moveFrom``, ...);
    ``comment_count`` is the number of populated ``w:comment`` elements. Every
    field is empty / zero for a clean document.
    """

    revision_parts: tuple[str, ...] = ()
    revision_kinds: tuple[str, ...] = ()
    comment_count: int = 0

    @property
    def has_tracked_revisions(self) -> bool:
        """True when any tracked-change/move/format/table revision markup is present."""
        return bool(self.revision_parts)

    @property
    def has_comments(self) -> bool:
        """True when the package carries at least one populated comment."""
        return self.comment_count > 0

    @property
    def is_clean(self) -> bool:
        """True when the package carries no revision markup and no comments."""
        return not self.revision_parts and self.comment_count == 0


def inspect_markup(path: str | Path) -> MarkupReport:
    """Inspect a ``.docx`` package for tracked/move/format/table revisions and comments.

    Returns a :class:`MarkupReport`. Propagates the underlying ``OSError`` /
    ``zipfile.BadZipFile`` if ``path`` cannot be opened as a ``.docx`` package --
    an un-inspectable file is never silently reported as clean; the caller's
    policy decides how to treat that.
    """
    revision_parts: list[str] = []
    revision_kinds: set[str] = set()
    comment_count = 0
    with ZipFile(path) as bundle:
        names = bundle.namelist()
        for name in names:
            if not (name.startswith(_CONTENT_PART_PREFIX) and name.endswith(_CONTENT_PART_SUFFIX)):
                continue
            found = _REVISION_TAG_RE.findall(bundle.read(name))
            if found:
                revision_parts.append(name)
                revision_kinds.update(kind.decode("ascii") for kind in found)
        if _COMMENTS_PART in names:
            comment_count = len(_COMMENT_TAG_RE.findall(bundle.read(_COMMENTS_PART)))
    return MarkupReport(
        revision_parts=tuple(sorted(revision_parts)),
        revision_kinds=tuple(sorted(revision_kinds)),
        comment_count=comment_count,
    )


def has_tracked_revisions(path: str | Path) -> bool:
    """True when the ``.docx`` at ``path`` carries any tracked/move/format/table revision."""
    return inspect_markup(path).has_tracked_revisions


def has_comments(path: str | Path) -> bool:
    """True when the ``.docx`` at ``path`` carries any populated comment."""
    return inspect_markup(path).has_comments

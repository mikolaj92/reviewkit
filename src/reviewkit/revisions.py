"""Accept every tracked revision in a reviewed ``.docx`` (Word "Accept All Changes").

reviewkit owns the OOXML tracked-change grammar (it *renders* reviewed DOCX with
real Word revisions in :mod:`reviewkit.renderer_docx`), so it also owns the inverse:
flattening a reviewed document into a clean one by accepting the markup exactly the
way Word's "Accept All Changes" command does. This keeps the czystopis / clean-copy
step from re-deriving the corrected text out of the original + plan; it consumes only
the reviewed document and honours whatever a human accepted, rejected or edited in it.

The transform runs over raw package XML (zipfile + lxml) rather than python-docx so
paragraph-mark insertions, moves and format-change records -- none of which python-docx
models -- are handled faithfully. Structural merges that dike never emits (accepting a
*paragraph-mark deletion*, which joins two paragraphs, or a *cell deletion*, which
removes a table cell) are refused fail-closed rather than approximated, so a surprising
input can never silently corrupt the clean copy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

from reviewkit.docx_package import _deterministic_zipinfo
from reviewkit.markup_purity import _REVISION_TAG_RE, inspect_markup

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_PART_PREFIX = "word/"
_CONTENT_PART_SUFFIX = ".xml"
_COMMENTS_PART = "word/comments.xml"

# The in-document comment anchors (they live in document.xml / headers / footers, not
# in comments.xml). ``inspect_markup`` counts comments only in comments.xml, but a
# clean copy must not leave dangling anchors pointing at an emptied comments part.
_COMMENT_ANCHOR_RE = re.compile(rb"<w:comment(Reference|RangeStart|RangeEnd)(?=[\s>/])")

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


class AcceptRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be accepted losslessly.

    Raised for the structural merges dike never emits (paragraph-mark or table-cell
    deletions) and as a fail-closed guard if the flattened output still carries markup.
    """


def _tag(name: str) -> str:
    return f"{{{_W}}}{name}"


def _remove(element: Any) -> None:
    # Drop ``element`` and its subtree, re-parenting the trailing text (``tail``) that
    # follows it so surrounding prose is never lost.
    parent = element.getparent()
    if parent is None:
        return
    if element.tail:
        previous = element.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + element.tail
        else:
            parent.text = (parent.text or "") + element.tail
    parent.remove(element)


def _unwrap(element: Any) -> None:
    # Replace ``element`` with its children in place (accept an insertion: keep the
    # inserted runs, drop the revision wrapper), preserving order and trailing text.
    parent = element.getparent()
    if parent is None:
        return
    children = list(element)
    for child in children:
        element.addprevious(child)
    if element.tail:
        if children:
            last = children[-1]
            last.tail = (last.tail or "") + element.tail
        else:
            previous = element.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + element.tail
            else:
                parent.text = (parent.text or "") + element.tail
    parent.remove(element)


def _is_paragraph_mark(element: Any) -> bool:
    # A run-property revision (paragraph glyph mark or run-property change) lives inside
    # a ``w:rPr``; a content revision wraps runs directly under a block element.
    parent = element.getparent()
    return parent is not None and parent.tag == _tag("rPr")


def _accept_revisions_in_tree(root: Any, part_name: str) -> None:
    # Refuse the structural merges we do not implement before touching anything, so a
    # failure leaves no half-transformed tree.
    for element in root.iter(_tag("cellDel")):
        raise AcceptRevisionsError(
            f"{part_name}: accepting a tracked cell deletion would remove a table cell; "
            "unsupported (dike never emits table-structure revisions)."
        )
    for element in root.iter(_tag("del"), _tag("moveFrom")):
        if _is_paragraph_mark(element):
            raise AcceptRevisionsError(
                f"{part_name}: accepting a tracked paragraph-mark deletion would merge two "
                "paragraphs; unsupported (dike never deletes a paragraph mark)."
            )

    # Deletions: the deleted content disappears when accepted.
    for element in list(root.iter(_tag("del"), _tag("moveFrom"))):
        _remove(element)

    # Insertions: the inserted content stays; a paragraph-mark insertion keeps the
    # paragraph (drop only the mark), a content insertion unwraps to its runs.
    for element in list(root.iter(_tag("ins"), _tag("moveTo"))):
        if element.getparent() is None:
            continue  # already gone (was nested inside an accepted deletion)
        if _is_paragraph_mark(element):
            _remove(element)
        else:
            _unwrap(element)

    # Property / table revision records: the *new* properties are already in place as
    # siblings; accepting just drops the change record.
    for name in (
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "trPrChange",
        "tcPrChange",
        "tblPrExChange",
        "tblGridChange",
        "numberingChange",
        "cellIns",
        "cellMerge",
    ):
        for element in list(root.iter(_tag(name))):
            _remove(element)


def _strip_comment_anchors(root: Any) -> None:
    for element in list(root.iter(_tag("commentRangeStart"), _tag("commentRangeEnd"))):
        _remove(element)
    for element in list(root.iter(_tag("commentReference"))):
        run = element.getparent()
        # Word wraps each reference in its own run; drop the whole run so no empty run
        # is left behind, falling back to the bare reference if the shape is unusual.
        _remove(run if run is not None and run.tag == _tag("r") else element)


def _serialize(root: Any) -> bytes:
    return (_XML_DECLARATION + etree.tostring(root, encoding="unicode")).encode("utf-8")


def _transform_part(name: str, data: bytes, *, drop_comments: bool) -> bytes:
    if name == _COMMENTS_PART and drop_comments:
        root = etree.fromstring(data)
        for child in list(root):
            root.remove(child)  # empty the comments part, preserving its namespaces
        return _serialize(root)

    needs_revisions = bool(_REVISION_TAG_RE.search(data))
    needs_comment_strip = drop_comments and bool(_COMMENT_ANCHOR_RE.search(data))
    if not (needs_revisions or needs_comment_strip):
        return data  # nothing to accept in this part; copy it through verbatim

    root = etree.fromstring(data)
    if needs_revisions:
        _accept_revisions_in_tree(root, name)
    if needs_comment_strip:
        _strip_comment_anchors(root)
    return _serialize(root)


def accept_all_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool = True,
) -> Path:
    """Flatten a reviewed ``.docx`` into a clean one by accepting every tracked change.

    Equivalent to Word's "Accept All Changes": every insertion is kept, every deletion
    is dropped, every move is realised, and every format-change record is discarded,
    leaving the *current* (post-review) content. ``drop_comments`` (default ``True``)
    also removes all comments and their in-document anchors. The single input is the
    reviewed document itself -- the corrected text is never re-derived from an original
    or a plan, so whatever a human accepted, rejected or edited in the reviewed copy is
    honoured exactly.

    Structural merges dike never emits are refused fail-closed via
    :class:`AcceptRevisionsError`: accepting a paragraph-mark deletion (which merges two
    paragraphs) or a table-cell deletion. As a post-condition the output is inspected
    with :func:`reviewkit.markup_purity.inspect_markup`; if any revision markup (or, when
    ``drop_comments``, any comment) survived, the call raises rather than emitting a
    document that still carries markup.

    Returns the ``out_path`` it wrote.
    """
    source = Path(reviewed_path)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Read the whole package into memory first so the transform is safe even when
    # out_path == reviewed_path (rewriting a document in place).
    with ZipFile(source) as bundle:
        entries = [(info, bundle.read(info.filename)) for info in bundle.infolist()]

    # Transform every part BEFORE opening the output: a fail-closed raise then leaves no
    # half-written .docx behind.
    transformed: list[tuple[Any, bytes]] = []
    for info, data in entries:
        if info.filename.startswith(_CONTENT_PART_PREFIX) and info.filename.endswith(
            _CONTENT_PART_SUFFIX
        ):
            data = _transform_part(info.filename, data, drop_comments=drop_comments)
        transformed.append((info, data))

    with ZipFile(destination, "w", ZIP_DEFLATED) as out:
        for info, data in transformed:
            # Preserve filename and per-part compression, but pin the entry timestamp: the
            # reviewed input carries the wall-clock mtime from whenever it was rendered, and
            # copying it through would make an otherwise-identical clean copy differ byte-for-
            # byte on every run.
            out.writestr(_deterministic_zipinfo(info), data)

    report = inspect_markup(destination)
    if report.has_tracked_revisions or (drop_comments and report.has_comments):
        raise AcceptRevisionsError(
            f"accept_all_revisions left markup in {destination}: "
            f"revision parts={report.revision_parts}, comments={report.comment_count}"
        )
    return destination


# Domain-facing alias: from the caller's side this "applies the reviewed markup" to
# produce the clean copy. Same operation, more intention-revealing name at call sites.
apply_reviewed_markup = accept_all_revisions

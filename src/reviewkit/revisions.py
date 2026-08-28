"""Accept or reject every tracked revision in a reviewed ``.docx``.

reviewkit owns the OOXML tracked-change grammar (it *renders* reviewed DOCX with
real Word revisions in :mod:`reviewkit.renderer_docx`), so it also owns both Word
inverses: Accept All and Reject All. Accept flattens to the current (post-review)
text; reject restores the pre-revision text. Downstream products can then derive a
clean copy or an approximate generated-original without re-implementing OOXML.

The transform runs over raw package XML (zipfile + lxml) rather than python-docx so
paragraph-mark insertions, moves and format-change records -- none of which python-docx
models -- are handled faithfully. Accepting a deleted paragraph mark and rejecting an
inserted paragraph mark merge adjacent paragraphs the way Word does. Table-cell
structural revisions (``cellDel``, and ``cellIns`` / ``cellMerge`` on reject) stay
fail-closed: a surprising input must never silently corrupt the clean copy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

from reviewkit.docx_package import _deterministic_zipinfo
from reviewkit.markup_purity import _revision_kinds_from_xml, inspect_markup

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_PART_PREFIX = "word/"
_CONTENT_PART_SUFFIX = ".xml"
_COMMENT_PART_PREFIXES = ("word/comments", "word/people.xml")
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
# The in-document comment anchors (they live in document.xml / headers / footers, not
# in comments.xml). ``inspect_markup`` counts comments only in comments.xml, but a
# clean copy must not leave dangling anchors pointing at an emptied comments part.
_COMMENT_ANCHOR_RE = re.compile(rb"<w:comment(Reference|RangeStart|RangeEnd)(?=[\s>/])")

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


class AcceptRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be accepted losslessly.

    Raised for unsupported table-cell structural revisions and as a fail-closed
    guard if the flattened output still carries markup.
    """


class RejectRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be rejected losslessly.

    Raised for unsupported table-cell structural revisions and as a fail-closed
    guard if the flattened output still carries markup.
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


def _is_paragraph_mark_revision(element: Any) -> bool:
    # Word stores a tracked paragraph-mark change as ``w:pPr/w:rPr/w:ins|w:del``.
    # Run-property revisions live in ``w:r/w:rPr`` and must not trigger a merge.
    if not _is_paragraph_mark(element):
        return False
    rpr = element.getparent()
    if rpr is None:
        return False
    ppr = rpr.getparent()
    return ppr is not None and ppr.tag == _tag("pPr")


def _paragraph_for_mark(element: Any) -> Any | None:
    rpr = element.getparent()
    if rpr is None:
        return None
    ppr = rpr.getparent()
    if ppr is None or ppr.tag != _tag("pPr"):
        return None
    paragraph = ppr.getparent()
    if paragraph is None or paragraph.tag != _tag("p"):
        return None
    return paragraph


def _restore_prior_properties(change: Any) -> None:
    # ``w:*PrChange`` stores the *previous* properties as a nested ``w:*Pr`` child.
    # The current properties already sit as siblings of the change record. Rejecting
    # replaces those siblings with the nested previous properties, unwrapping the
    # extra ``w:*Pr`` so we never nest ``w:rPr`` inside ``w:rPr``.
    parent = change.getparent()
    if parent is None:
        return
    previous = list(change)
    if len(previous) == 1 and previous[0].tag == parent.tag:
        previous = list(previous[0])
    for sibling in list(parent):
        if sibling is change:
            continue
        parent.remove(sibling)
    for child in previous:
        change.addprevious(child)
    _remove(change)


def _merge_with_next_paragraph(paragraph: Any) -> None:
    parent = paragraph.getparent()
    if parent is None:
        return  # already absorbed by an earlier paragraph-mark merge
    nxt = paragraph.getnext()
    if nxt is None or nxt.tag != _tag("p"):
        return  # last paragraph, or a trailing sectPr; dropping the mark is enough
    # Keep this paragraph's properties; move only the next paragraph's content.
    for child in list(nxt):
        if child.tag == _tag("pPr"):
            continue
        paragraph.append(child)
    _remove(nxt)


def _paragraphs_with_mark(root: Any, *revision_tags: str) -> list[Any]:
    seen: set[int] = set()
    paragraphs: list[Any] = []
    for element in root.iter(*(_tag(name) for name in revision_tags)):
        if not _is_paragraph_mark_revision(element):
            continue
        paragraph = _paragraph_for_mark(element)
        if paragraph is None:
            continue
        marker = id(paragraph)
        if marker in seen:
            continue
        seen.add(marker)
        paragraphs.append(paragraph)
    paragraphs.reverse()
    return paragraphs


def _drop_empty_revision_leftover(paragraph: Any) -> None:
    """Drop a paragraph emptied by rejecting an inserted numbered item.

    Word keeps ``w:numPr`` on a paragraph whose only content was a rejected
    insertion, leaving a blank numbered slot or a stray digit. Remove that
    leftover only when the paragraph has no remaining visible or deleted text.
    Unrelated empty numbered items stay.
    """
    if paragraph.getparent() is None:
        return
    if any((node.text or "").strip() for node in paragraph.iter(_tag("t"), _tag("delText"))):
        return
    ppr = paragraph.find(_tag("pPr"))
    if ppr is None or ppr.find(_tag("numPr")) is None:
        return
    _remove(paragraph)


def _accept_revisions_in_tree(root: Any, part_name: str) -> None:
    # Refuse table-cell structural revisions we do not implement before touching
    # anything, so a failure leaves no half-transformed tree.
    for element in root.iter(_tag("cellDel")):
        raise AcceptRevisionsError(
            f"{part_name}: accepting a tracked cell deletion would remove a table cell; "
            "unsupported."
        )

    # Accepting a deleted paragraph mark merges this paragraph with the next one,
    # matching Word. Walk from the end so consecutive marks still join.
    for paragraph in _paragraphs_with_mark(root, "del", "moveFrom"):
        ppr = paragraph.find(_tag("pPr"))
        rpr = None if ppr is None else ppr.find(_tag("rPr"))
        if rpr is not None:
            for mark in list(rpr.iter(_tag("del"), _tag("moveFrom"))):
                _remove(mark)
        _merge_with_next_paragraph(paragraph)
    for element in list(root.iter(_tag("del"), _tag("moveFrom"))):
        if element.getparent() is None:
            continue
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


def _restore_deleted_text(root: Any) -> None:
    """``w:delText`` is invisible once the ``w:del`` wrapper is gone."""
    visible = _tag("t")
    for element in root.iter(_tag("delText")):
        element.tag = visible


def _reject_revisions_in_tree(root: Any, part_name: str) -> None:
    for element in root.iter(_tag("cellDel"), _tag("cellIns"), _tag("cellMerge")):
        raise RejectRevisionsError(
            f"{part_name}: rejecting a tracked cell revision would change table structure; "
            "unsupported."
        )

    leftover_paragraphs: list[Any] = []
    for paragraph in _paragraphs_with_mark(root, "ins", "moveTo"):
        ppr = paragraph.find(_tag("pPr"))
        rpr = None if ppr is None else ppr.find(_tag("rPr"))
        if rpr is not None:
            for mark in list(rpr.iter(_tag("ins"), _tag("moveTo"))):
                _remove(mark)
        _merge_with_next_paragraph(paragraph)
        leftover_paragraphs.append(paragraph)
    for element in list(root.iter(_tag("ins"), _tag("moveTo"))):
        if element.getparent() is None:
            continue
        if _is_paragraph_mark(element):
            _remove(element)
            continue
        parent = element.getparent()
        _remove(element)
        if parent is not None and parent.tag == _tag("p"):
            leftover_paragraphs.append(parent)

    for element in list(root.iter(_tag("del"), _tag("moveFrom"))):
        if element.getparent() is None:
            continue
        if _is_paragraph_mark(element):
            _remove(element)
        else:
            _unwrap(element)
    _restore_deleted_text(root)

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
    ):
        for element in list(root.iter(_tag(name))):
            _restore_prior_properties(element)

    for paragraph in leftover_paragraphs:
        _drop_empty_revision_leftover(paragraph)


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


def _is_comment_part(name: str) -> bool:
    return name.startswith(_COMMENT_PART_PREFIXES)


def _strip_comment_relationships(data: bytes) -> bytes:
    root = etree.fromstring(data)
    changed = False
    for relationship in list(root):
        if relationship.tag != f"{{{_RELATIONSHIPS_NS}}}Relationship":
            continue
        target = relationship.get("Target", "").removeprefix("/")
        relationship_type = relationship.get("Type", "")
        if "comment" in relationship_type.lower() or target.startswith(
            ("comments", "word/comments", "people.xml", "word/people.xml")
        ):
            root.remove(relationship)
            changed = True
    return _serialize(root) if changed else data


def _strip_comment_content_types(data: bytes) -> bytes:
    root = etree.fromstring(data)
    changed = False
    for override in list(root):
        if override.tag != f"{{{_CONTENT_TYPES_NS}}}Override":
            continue
        part_name = override.get("PartName", "").removeprefix("/")
        if _is_comment_part(part_name):
            root.remove(override)
            changed = True
    return _serialize(root) if changed else data


def _transform_part(
    name: str,
    data: bytes,
    *,
    drop_comments: bool,
    reject: bool,
) -> bytes:
    if drop_comments and name.endswith(".rels"):
        return _strip_comment_relationships(data)
    if drop_comments and name == "[Content_Types].xml":
        return _strip_comment_content_types(data)

    needs_revisions = bool(_revision_kinds_from_xml(data))
    needs_comment_strip = drop_comments and bool(_COMMENT_ANCHOR_RE.search(data))
    if not (needs_revisions or needs_comment_strip):
        return data  # nothing to flatten in this part; copy it through verbatim

    root = etree.fromstring(data)
    if needs_revisions:
        if reject:
            _reject_revisions_in_tree(root, name)
        else:
            _accept_revisions_in_tree(root, name)
    if needs_comment_strip:
        _strip_comment_anchors(root)
    return _serialize(root)


def _flatten_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool,
    reject: bool,
    error_type: type[Exception],
    operation: str,
) -> Path:
    source = Path(reviewed_path)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Read the whole package into memory first so the transform is safe even when
    # out_path == reviewed_path (rewriting a document in place).
    with ZipFile(source) as bundle:
        entries = [(info, bundle.read(info.filename)) for info in bundle.infolist()]

    if drop_comments:
        entries = [(info, data) for info, data in entries if not _is_comment_part(info.filename)]

    # Transform every part BEFORE opening the output: a fail-closed raise then leaves no
    # half-written .docx behind.
    transformed: list[tuple[Any, bytes]] = []
    for info, data in entries:
        if (
            (
                info.filename.startswith(_CONTENT_PART_PREFIX)
                and info.filename.endswith(_CONTENT_PART_SUFFIX)
            )
            or info.filename.endswith(".rels")
            or info.filename == "[Content_Types].xml"
        ):
            data = _transform_part(info.filename, data, drop_comments=drop_comments, reject=reject)
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
        destination.unlink(missing_ok=True)
        raise error_type(
            f"{operation} left markup in {destination}: "
            f"revision parts={report.revision_parts}, comments={report.comment_count}"
        )
    return destination


def accept_all_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool = True,
) -> Path:
    """Flatten a reviewed ``.docx`` into a clean one by accepting every tracked change.

    Equivalent to Word's "Accept All Changes": every insertion is kept, every deletion
    is dropped, every move is realised, and every format-change record is discarded,
    leaving the *current* (post-review) content. Accepting a deleted paragraph mark
    merges that paragraph with the next one. ``drop_comments`` (default ``True``)
    also removes all comments and their in-document anchors. The single input is the
    reviewed document itself -- the corrected text is never re-derived from an original
    or a plan, so whatever a human accepted, rejected or edited in the reviewed copy is
    honoured exactly.

    Unsupported table-cell structural revisions are refused fail-closed via
    :class:`AcceptRevisionsError`. As a post-condition the output is inspected with
    :func:`reviewkit.markup_purity.inspect_markup`; if any revision markup (or, when
    ``drop_comments``, any comment) survived, the call raises rather than emitting a
    document that still carries markup.

    Returns the ``out_path`` it wrote.
    """
    return _flatten_revisions(
        reviewed_path,
        out_path,
        drop_comments=drop_comments,
        reject=False,
        error_type=AcceptRevisionsError,
        operation="accept_all_revisions",
    )


def reject_all_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool = True,
) -> Path:
    """Flatten a reviewed ``.docx`` by rejecting every tracked change.

    Equivalent to Word's "Reject All Changes": insertions disappear, deletions are
    restored, and rejecting an inserted paragraph mark merges that paragraph with the
    next one. The result is an *approximate generated-original*, not a historical
    source document. ``drop_comments`` (default ``True``) also removes comments and
    their in-document anchors.

    Unsupported table-cell structural revisions are refused fail-closed via
    :class:`RejectRevisionsError` before a partial output is written. As a
    post-condition the output is inspected with :func:`inspect_markup`; leftover
    markup deletes the destination and raises.

    Returns the ``out_path`` it wrote.
    """
    return _flatten_revisions(
        reviewed_path,
        out_path,
        drop_comments=drop_comments,
        reject=True,
        error_type=RejectRevisionsError,
        operation="reject_all_revisions",
    )


# Domain-facing alias: from the caller's side this "applies the reviewed markup" to
# produce the clean copy. Same operation, more intention-revealing name at call sites.
apply_reviewed_markup = accept_all_revisions

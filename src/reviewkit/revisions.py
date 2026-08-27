"""Accept every tracked revision in a reviewed ``.docx`` (Word "Accept All Changes").

reviewkit owns the OOXML tracked-change grammar (it *renders* reviewed DOCX with
real Word revisions in :mod:`reviewkit.renderer_docx`), so it also owns the inverse:
flattening a reviewed document into a clean one by accepting the markup exactly the
way Word's "Accept All Changes" command does. This keeps the czystopis / clean-copy
step from re-deriving the corrected text out of the original + plan; it consumes only
the reviewed document and honours whatever a human accepted, rejected or edited in it.

The transform runs over raw package XML (zipfile + lxml) rather than python-docx so
paragraph-mark insertions, moves and format-change records -- none of which python-docx
models -- are handled faithfully. Paragraph-mark deletions join the affected paragraphs.
Table-cell deletions remain unsupported and fail closed rather than being approximated,
so a surprising input can never silently corrupt the clean copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reviewkit.markup_purity import inspect_markup
from reviewkit.revision_paragraphs import (
    drop_paired_range_revision_markers,
    is_content_control_paragraph,
    merge_paragraph_into_next,
)
from reviewkit.revision_package import (
    RevisionPackageError,
    has_comment_anchors,
    is_comment_part,
    parse_xml,
    read_package_entries,
    revision_kinds,
    serialize,
    strip_comment_anchors,
    strip_comment_content_types,
    strip_comment_relationships,
    write_package_atomically,
)
from reviewkit.revision_rejection import RejectRevisionsError, reject_all_revisions

__all__ = [
    "AcceptRevisionsError",
    "RejectRevisionsError",
    "accept_all_revisions",
    "apply_reviewed_markup",
    "reject_all_revisions",
]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_STRICT_W = "http://purl.oclc.org/ooxml/wordprocessingml/main"

_CONTENT_PART_PREFIX = "word/"
_CONTENT_PART_SUFFIX = ".xml"


class AcceptRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be accepted losslessly.

    Raised when a structural revision cannot be flattened without guessing and when
    the flattened output still carries review markup.
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
    properties = parent.getparent() if parent is not None else None
    paragraph = properties.getparent() if properties is not None else None
    return (
        parent is not None
        and parent.tag == _tag("rPr")
        and properties is not None
        and properties.tag == _tag("pPr")
        and paragraph is not None
        and paragraph.tag == _tag("p")
    )


def _accept_revisions_in_tree(root: Any, part_name: str) -> None:
    # Refuse the structural merges we do not implement before touching anything, so a
    # failure leaves no half-transformed tree.
    for name in ("cellDel", "cellIns", "cellMerge"):
        if next(root.iter(_tag(name)), None) is not None:
            raise AcceptRevisionsError(f"{part_name}: accepting {name} is unsupported")
    invalid_range = drop_paired_range_revision_markers(root, _W)
    if invalid_range is not None:
        raise AcceptRevisionsError(f"{part_name}: accepting {invalid_range}")
    for element in list(root.iter(_tag("del"), _tag("moveFrom"))):
        if _is_paragraph_mark(element) and element.getparent() is not None:
            if not merge_paragraph_into_next(element, _W):
                if is_content_control_paragraph(element, _W):
                    _remove(element)
                else:
                    raise AcceptRevisionsError(
                        f"{part_name}: tracked paragraph-mark deletion has no following paragraph"
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


def _transform_part(name: str, data: bytes, *, drop_comments: bool) -> bytes:
    if drop_comments and name.endswith(".rels"):
        return strip_comment_relationships(data)
    if drop_comments and name == "[Content_Types].xml":
        return strip_comment_content_types(data)

    root = parse_xml(data)
    strict_revisions = revision_kinds(root, _STRICT_W)
    strict_comment_anchors = drop_comments and has_comment_anchors(root, _STRICT_W)
    if strict_revisions or strict_comment_anchors:
        raise AcceptRevisionsError(
            f"{name}: strict WordprocessingML review markup is unsupported"
        )
    needs_revisions = bool(revision_kinds(root, _W))
    needs_comment_strip = drop_comments and has_comment_anchors(root, _W)
    if not (needs_revisions or needs_comment_strip):
        return data  # nothing to accept in this part; copy it through verbatim

    if needs_revisions:
        _accept_revisions_in_tree(root, name)
    if needs_comment_strip:
        strip_comment_anchors(root, _W)
    return serialize(root)


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

    Table-cell deletion is refused fail-closed via :class:`AcceptRevisionsError`. As a
    post-condition the output is inspected with
    :func:`reviewkit.markup_purity.inspect_markup`; if any revision markup (or, when
    ``drop_comments``, any comment) survived, the call raises rather than emitting a
    document that still carries markup.

    Returns the ``out_path`` it wrote.
    """
    source = Path(reviewed_path)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Read the whole package into memory first so the transform is safe even when
    # out_path == reviewed_path (rewriting a document in place).
    try:
        entries = read_package_entries(source)
    except RevisionPackageError as exc:
        raise AcceptRevisionsError(str(exc)) from exc

    if drop_comments:
        entries = [(info, data) for info, data in entries if not is_comment_part(info.filename)]

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
            data = _transform_part(info.filename, data, drop_comments=drop_comments)
        transformed.append((info, data))

    def validate(path: Path) -> None:
        report = inspect_markup(path)
        if report.has_tracked_revisions or (drop_comments and report.has_comments):
            raise AcceptRevisionsError(
                f"accept_all_revisions left markup in {destination}: "
                f"revision parts={report.revision_parts}, comments={report.comment_count}"
            )

    write_package_atomically(destination, transformed, validate)
    return destination


# Domain-facing alias: from the caller's side this "applies the reviewed markup" to
# produce the clean copy. Same operation, more intention-revealing name at call sites.
apply_reviewed_markup = accept_all_revisions

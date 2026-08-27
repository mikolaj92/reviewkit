"""Reject every tracked revision in a reviewed DOCX (Word "Reject All Changes")."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import etree

from reviewkit.docx_package import _deterministic_zipinfo
from reviewkit.markup_purity import _REVISION_TAG_RE, inspect_markup
from reviewkit.revision_package import (
    COMMENT_ANCHOR_RE,
    is_comment_part,
    serialize,
    strip_comment_anchors,
    strip_comment_content_types,
    strip_comment_relationships,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_PART_PREFIX = "word/"
_CONTENT_PART_SUFFIX = ".xml"
_BODY_MARKER_TAGS = frozenset(
    (
        f"{{{_W}}}bookmarkStart",
        f"{{{_W}}}bookmarkEnd",
        f"{{{_W}}}permStart",
        f"{{{_W}}}permEnd",
        f"{{{_W}}}proofErr",
    )
)
_COMMENT_RANGE_TAGS = frozenset((f"{{{_W}}}commentRangeStart", f"{{{_W}}}commentRangeEnd"))
_INSERTION_TAGS = frozenset((f"{{{_W}}}ins", f"{{{_W}}}moveTo"))
_NON_TEXT_CONTENT_TAGS = tuple(
    f"{{{_W}}}{name}" for name in ("tab", "br", "cr", "drawing", "object", "pict", "fldChar", "sym")
)


class RejectRevisionsError(RuntimeError):
    """A reviewed document carries markup that cannot be rejected losslessly."""


def _tag(name: str) -> str:
    return f"{{{_W}}}{name}"


def _remove(element: etree._Element) -> None:
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


def _unwrap(element: etree._Element) -> None:
    parent = element.getparent()
    if parent is None:
        return
    children = list(element)
    for child in children:
        element.addprevious(child)
    if element.tail:
        if children:
            children[-1].tail = (children[-1].tail or "") + element.tail
        else:
            previous = element.getprevious()
            if previous is not None:
                previous.tail = (previous.tail or "") + element.tail
            else:
                parent.text = (parent.text or "") + element.tail
    parent.remove(element)


def _is_paragraph_mark(element: etree._Element) -> bool:
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


def _merge_paragraph_into_next(mark: etree._Element, part_name: str) -> None:
    run_properties = mark.getparent()
    paragraph_properties = run_properties.getparent() if run_properties is not None else None
    paragraph = paragraph_properties.getparent() if paragraph_properties is not None else None
    next_paragraph = paragraph.getnext() if paragraph is not None else None
    if (
        paragraph is None
        or paragraph.tag != _tag("p")
        or next_paragraph is None
        or next_paragraph.tag != _tag("p")
    ):
        raise RejectRevisionsError(
            f"{part_name}: tracked paragraph-mark insertion has no following paragraph"
        )
    insert_at = 1 if len(next_paragraph) and next_paragraph[0].tag == _tag("pPr") else 0
    for child in [node for node in paragraph if node.tag != _tag("pPr")]:
        next_paragraph.insert(insert_at, child)
        insert_at += 1
    parent = paragraph.getparent()
    if parent is None:
        raise RejectRevisionsError(f"{part_name}: tracked paragraph has no parent")
    parent.remove(paragraph)


def _paragraph_has_original_content(paragraph: etree._Element) -> bool:
    for node in paragraph.iter(_tag("t"), _tag("delText"), *_NON_TEXT_CONTENT_TAGS):
        if node.tag in {_tag("t"), _tag("delText")} and not (node.text or "").strip():
            continue
        if not any(
            ancestor.tag in {_tag("ins"), _tag("moveTo")} for ancestor in node.iterancestors()
        ):
            return True
    return False


def _is_comment_reference_run(element: etree._Element) -> bool:
    return element.tag == _tag("r") and element.find(f".//{_tag('commentReference')}") is not None


def _reject_inserted_paragraph_mark(
    mark: etree._Element, part_name: str, *, drop_comments: bool
) -> None:
    run_properties = mark.getparent()
    paragraph_properties = run_properties.getparent() if run_properties is not None else None
    paragraph = paragraph_properties.getparent() if paragraph_properties is not None else None
    if paragraph is None or paragraph.tag != _tag("p"):
        raise RejectRevisionsError(f"{part_name}: malformed paragraph-mark insertion")
    if _paragraph_has_original_content(paragraph):
        _merge_paragraph_into_next(mark, part_name)
        return

    unexpected = [
        child.tag
        for child in paragraph
        if child.tag != _tag("pPr")
        and child.tag not in _INSERTION_TAGS
        and child.tag not in _BODY_MARKER_TAGS
        and not (
            drop_comments and (child.tag in _COMMENT_RANGE_TAGS or _is_comment_reference_run(child))
        )
    ]
    if unexpected:
        raise RejectRevisionsError(
            f"{part_name}: inserted paragraph contains unsupported structural children"
        )
    for child in list(paragraph):
        if child.tag in _BODY_MARKER_TAGS:
            paragraph.addprevious(child)
    parent = paragraph.getparent()
    if parent is None:
        raise RejectRevisionsError(f"{part_name}: tracked paragraph has no parent")
    parent.remove(paragraph)


def _reject_revisions_in_tree(root: etree._Element, part_name: str, *, drop_comments: bool) -> None:
    for _element in root.iter(_tag("cellDel")):
        raise RejectRevisionsError(f"{part_name}: rejecting a tracked cell deletion is unsupported")
    for element in list(root.iter(_tag("ins"), _tag("moveTo"))):
        if _is_paragraph_mark(element) and element.getparent() is not None:
            _reject_inserted_paragraph_mark(element, part_name, drop_comments=drop_comments)

    for element in list(root.iter(_tag("ins"), _tag("moveTo"))):
        if element.getparent() is not None:
            _remove(element)

    for element in list(root.iter(_tag("del"), _tag("moveFrom"))):
        if element.getparent() is None:
            continue
        if _is_paragraph_mark(element):
            _remove(element)
        else:
            _unwrap(element)
    _restore_deleted_text(root)
    _restore_property_changes(root, part_name)

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


def _restore_deleted_text(root: etree._Element) -> None:
    for element in root.iter(_tag("delText")):
        element.tag = _tag("t")


def _restore_property_changes(root: etree._Element, part_name: str) -> None:
    for change_name, property_name in (("rPrChange", "rPr"), ("pPrChange", "pPr")):
        for change in list(root.iter(_tag(change_name))):
            parent = change.getparent()
            snapshot = change.find(_tag(property_name))
            if parent is None or snapshot is None:
                raise RejectRevisionsError(f"{part_name}: malformed {change_name}")
            for child in list(parent):
                parent.remove(child)
            for child in snapshot:
                parent.append(deepcopy(child))


def _transform_part(name: str, data: bytes, *, drop_comments: bool) -> bytes:
    if drop_comments and name.endswith(".rels"):
        return strip_comment_relationships(data)
    if drop_comments and name == "[Content_Types].xml":
        return strip_comment_content_types(data)

    needs_revisions = bool(_REVISION_TAG_RE.search(data))
    needs_comment_strip = drop_comments and bool(COMMENT_ANCHOR_RE.search(data))
    if not (needs_revisions or needs_comment_strip):
        return data

    root = etree.fromstring(data)
    if needs_revisions:
        _reject_revisions_in_tree(root, name, drop_comments=drop_comments)
    if needs_comment_strip:
        strip_comment_anchors(root, _W)
    return serialize(root)


def reject_all_revisions(
    reviewed_path: str | Path,
    out_path: str | Path,
    *,
    drop_comments: bool = True,
) -> Path:
    """Flatten a reviewed DOCX to its pre-revision view by rejecting all changes."""
    source = Path(reviewed_path)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(source) as bundle:
        entries = [(info, bundle.read(info.filename)) for info in bundle.infolist()]
    if drop_comments:
        entries = [(info, data) for info, data in entries if not is_comment_part(info.filename)]

    transformed: list[tuple[ZipInfo, bytes]] = []
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

    with ZipFile(destination, "w", ZIP_DEFLATED) as output:
        for info, data in transformed:
            output.writestr(_deterministic_zipinfo(info), data)

    report = inspect_markup(destination)
    if report.has_tracked_revisions or (drop_comments and report.has_comments):
        destination.unlink(missing_ok=True)
        raise RejectRevisionsError(
            f"reject_all_revisions left markup in {destination}: "
            f"revision parts={report.revision_parts}, comments={report.comment_count}"
        )
    return destination

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from zipfile import ZipInfo

from docxtor import (
    PackageEntry,
    PackageError,
    PackageLimits,
    parse_package_xml,
    read_package_entries as read_docx_package_entries,
    write_package_atomically as write_docx_package_atomically,
)
from lxml import etree

_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
MAX_PACKAGE_ENTRIES = 4096
MAX_ENTRY_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000

REVISION_NAMES = (
    "ins",
    "del",
    "moveFrom",
    "moveTo",
    "rPrChange",
    "pPrChange",
    "sectPrChange",
    "tblPrChange",
    "trPrChange",
    "tcPrChange",
    "cellIns",
    "cellDel",
    "cellMerge",
    "tblGridChange",
    "tblPrExChange",
    "numberingChange",
    "moveFromRangeStart",
    "moveFromRangeEnd",
    "moveToRangeStart",
    "moveToRangeEnd",
    "customXmlDelRangeStart",
    "customXmlDelRangeEnd",
    "customXmlInsRangeStart",
    "customXmlInsRangeEnd",
    "customXmlMoveFromRangeStart",
    "customXmlMoveFromRangeEnd",
    "customXmlMoveToRangeStart",
    "customXmlMoveToRangeEnd",
    "conflictIns",
    "conflictDel",
    "customXmlConflictInsRangeStart",
    "customXmlConflictInsRangeEnd",
    "customXmlConflictDelRangeStart",
    "customXmlConflictDelRangeEnd",
)
class RevisionPackageError(RuntimeError):
    pass


def read_package_entries(path: Path) -> list[tuple[ZipInfo, bytes]]:
    """Compatibility projection over Docxtor's canonical safe package reader."""
    try:
        entries = read_docx_package_entries(
            path,
            limits=PackageLimits(
                max_entries=MAX_PACKAGE_ENTRIES,
                max_entry_uncompressed_bytes=MAX_ENTRY_UNCOMPRESSED_BYTES,
                max_total_uncompressed_bytes=MAX_TOTAL_UNCOMPRESSED_BYTES,
                max_compression_ratio=MAX_COMPRESSION_RATIO,
            ),
        )
    except PackageError as exc:
        raise RevisionPackageError(str(exc)) from exc
    projected: list[tuple[ZipInfo, bytes]] = []
    for entry in entries:
        projected.append((entry.zip_info(), entry.data))
    return projected


def parse_xml(data: bytes) -> etree._Element:
    """Parse package XML through Docxtor's canonical fail-closed parser."""
    try:
        return parse_package_xml(data)
    except PackageError as exc:
        raise RevisionPackageError(str(exc)) from exc


def revision_kinds(root: etree._Element, word_namespace: str) -> set[str]:
    return {
        name
        for name in REVISION_NAMES
        if next(root.iter(f"{{{word_namespace}}}{name}"), None) is not None
    }


def has_comment_anchors(root: etree._Element, word_namespace: str) -> bool:
    return any(
        next(root.iter(f"{{{word_namespace}}}{name}"), None) is not None
        for name in ("commentReference", "commentRangeStart", "commentRangeEnd")
    )


def serialize(root: etree._Element) -> bytes:
    return (_XML_DECLARATION + etree.tostring(root, encoding="unicode")).encode()


def is_comment_part(name: str) -> bool:
    normalized = name.removeprefix("/")
    if not normalized.startswith("word/"):
        return False
    basename = normalized.rsplit("/", 1)[-1]
    if basename == "people.xml" or (
        basename.startswith("comments") and basename.endswith(".xml")
    ):
        return True
    if normalized.startswith("word/_rels/") and basename.endswith(".xml.rels"):
        source_part = basename.removesuffix(".rels")
        return source_part == "people.xml" or (
            source_part.startswith("comments") and source_part.endswith(".xml")
        )
    return False


def write_package_atomically(
    destination: Path,
    entries: list[tuple[ZipInfo, bytes]],
    validate: Callable[[Path], None],
) -> None:
    """Delegate neutral atomic DOCX publication to Docxtor."""
    records = [PackageEntry.from_zip(info, data) for info, data in entries]
    try:
        write_docx_package_atomically(destination, records, validate=validate)
    except PackageError as exc:
        raise RevisionPackageError(str(exc)) from exc


def strip_comment_anchors(root: etree._Element, word_namespace: str) -> None:
    def tag(name: str) -> str:
        return f"{{{word_namespace}}}{name}"

    for element in list(root.iter(tag("commentRangeStart"), tag("commentRangeEnd"))):
        _remove(element)
    for element in list(root.iter(tag("commentReference"))):
        run = element.getparent()
        _remove(run if run is not None and run.tag == tag("r") else element)


def strip_comment_relationships(data: bytes) -> bytes:
    root = parse_xml(data)
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
    return serialize(root) if changed else data


def strip_comment_content_types(data: bytes) -> bytes:
    root = parse_xml(data)
    changed = False
    for override in list(root):
        if override.tag != f"{{{_CONTENT_TYPES_NS}}}Override":
            continue
        part_name = override.get("PartName", "").removeprefix("/")
        if is_comment_part(part_name):
            root.remove(override)
            changed = True
    return serialize(root) if changed else data


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

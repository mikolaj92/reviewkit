from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import etree

from reviewkit.docx_package import _deterministic_zipinfo

_COMMENT_PART_PREFIXES = ("word/comments", "word/people.xml")
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
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
)
MAX_PACKAGE_ENTRIES = 4096
MAX_ENTRY_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1000


class RevisionPackageError(RuntimeError):
    pass


def read_package_entries(path: Path) -> list[tuple[ZipInfo, bytes]]:
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_PACKAGE_ENTRIES:
            raise RevisionPackageError(
                f"DOCX has {len(infos)} entries; limit is {MAX_PACKAGE_ENTRIES}"
            )
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise RevisionPackageError("DOCX contains duplicate package member names")
        total = sum(info.file_size for info in infos)
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise RevisionPackageError(
                f"DOCX uncompressed size {total} exceeds {MAX_TOTAL_UNCOMPRESSED_BYTES}"
            )
        for info in infos:
            if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
                raise RevisionPackageError(
                    f"DOCX entry {info.filename} uncompressed size exceeds limit"
                )
            ratio = info.file_size / max(info.compress_size, 1)
            if ratio > MAX_COMPRESSION_RATIO:
                raise RevisionPackageError(
                    f"DOCX entry {info.filename} compression ratio exceeds limit"
                )
        return [(info, archive.read(info)) for info in infos]


def parse_xml(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(data, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise RevisionPackageError("DOCX XML must not contain a DOCTYPE declaration")
    return root


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
    return name.startswith(_COMMENT_PART_PREFIXES)


def write_package_atomically(
    destination: Path,
    entries: list[tuple[ZipInfo, bytes]],
    validate: Callable[[Path], None],
) -> None:
    with NamedTemporaryFile(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as output:
            for info, data in entries:
                output.writestr(_deterministic_zipinfo(info), data)
        validate(temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


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

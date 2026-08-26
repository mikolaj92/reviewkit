"""Word comment read API: structured comments with body anchors.

Existing Word comments are review input. This module is the one-job owner of
that read: each comment's id, author, visible text, and the body range it is
anchored to (locator + quoted text). Consumers such as Dike join
``anchor_text`` / paragraph text with ``text`` for the LLM.

python-docx models comment *bodies* but not the reference range and not the
modern thread parts (``commentsExtended.xml``, ``people.xml``, ...). Range
anchors are recovered from the package XML; thread parts are copied back after
a python-docx save so existing threads are not dropped. This module does not
fork python-docx and does not rewrite Word comment markup.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile, ZipInfo

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from reviewkit.docx_package import _deterministic_zipinfo

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
_W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_COMMENTS_PART = "word/comments.xml"
_COMMENTS_EXTENDED_PART = "word/commentsExtended.xml"
_DOCUMENT_RELS_PART = "word/_rels/document.xml.rels"
_CONTENT_TYPES_PART = "[Content_Types].xml"

# Package parts that carry modern Word comment *threads* (replies, done-state,
# durable ids, people). python-docx 1.2 does not model them, so a save drops
# any part that is not in the relationship graph it walked.
_THREAD_PART_PREFIXES = (
    "word/commentsExtended",
    "word/commentsIds",
    "word/commentsExtensible",
    "word/people.xml",
    "word/_rels/comments",
    "word/_rels/people",
)

_THREAD_REL_TARGETS = frozenset(
    {
        "commentsExtended.xml",
        "commentsIds.xml",
        "commentsExtensible.xml",
        "people.xml",
    }
)


@dataclass(frozen=True)
class DocxComment:
    """One Word comment: identity, body, and the source range it is anchored to."""

    id: str
    author: str
    initials: str
    text: str
    locator: str | None = None
    anchor_text: str = ""
    parent_id: str | None = None


def read_comments(path: str | Path) -> list[DocxComment]:
    """Return every comment as a structured record with its body anchor.

    ``text`` / ``author`` / ``initials`` come from python-docx's public comments
    collection (the same model the renderer writes through). The anchor is the
    visible body text between ``w:commentRangeStart`` and ``w:commentRangeEnd``
    plus the paragraph locator used by ``load_docx``. Replies carry ``parent_id``
    when ``commentsExtended.xml`` names a parent. Returns an empty list when the
    package carries no comments (or cannot be opened as a package).
    """
    try:
        docx = DocxDocument(str(path))
    except (OSError, PackageNotFoundError):
        return []

    anchors = _comment_anchors(docx)
    parents = _comment_parent_ids(path)
    comments: list[DocxComment] = []
    for comment in docx.comments:
        comment_id = str(comment.comment_id)
        locator, anchor_text = anchors.get(comment_id, (None, ""))
        comments.append(
            DocxComment(
                id=comment_id,
                author=comment.author or "",
                initials=comment.initials or "",
                text=comment.text,
                locator=locator,
                anchor_text=anchor_text,
                parent_id=parents.get(comment_id),
            )
        )
    return comments


def comments_for_locator(
    comments: list[DocxComment], locator: str | None
) -> list[DocxComment]:
    """Comments whose range starts in the paragraph identified by ``locator``."""
    if not locator:
        return []
    return [comment for comment in comments if comment.locator == locator]


def restore_comment_thread_parts(source_path: str | Path, rendered_path: str | Path) -> None:
    """Copy modern comment-thread parts that python-docx dropped on save.

    ``comments.xml`` is left alone: the renderer appends new review comments
    there. Only the thread sidecar parts (and the relationships / content-type
    entries that make Word see them) are restored from the source package.
    """
    source = Path(source_path)
    target = Path(rendered_path)
    with ZipFile(source) as bundle:
        source_parts = {
            name: bundle.read(name)
            for name in bundle.namelist()
            if _is_thread_part(name)
            or name in {_DOCUMENT_RELS_PART, _CONTENT_TYPES_PART}
        }

    if not any(_is_thread_part(name) for name in source_parts):
        return

    with ZipFile(target) as rendered:
        rendered_names = set(rendered.namelist())
        entries = [(info, rendered.read(info.filename)) for info in rendered.infolist()]

    missing = {
        name: data
        for name, data in source_parts.items()
        if _is_thread_part(name) and name not in rendered_names
    }
    if not missing:
        return

    restored: list[tuple[Any, bytes]] = []
    for info, data in entries:
        name = info.filename
        if name == _CONTENT_TYPES_PART:
            data = _merge_content_type_overrides(
                data, source_parts.get(_CONTENT_TYPES_PART, b""), missing
            )
        elif name == _DOCUMENT_RELS_PART:
            data = _merge_document_relationships(
                data, source_parts.get(_DOCUMENT_RELS_PART, b""), missing
            )
        restored.append((info, data))

    for name, data in sorted(missing.items()):
        restored.append((_deterministic_zipinfo(ZipInfo(name)), data))

    with ZipFile(target, "w") as output:
        for info, data in restored:
            output.writestr(info, data)


def _is_thread_part(name: str) -> bool:
    return name.startswith(_THREAD_PART_PREFIXES)


def _comment_anchors(docx: Any) -> dict[str, tuple[str, str]]:
    """Map comment id -> (paragraph locator, visible anchored text)."""
    open_ids: dict[str, list[str]] = {}
    started_at: dict[str, str] = {}
    finished: dict[str, tuple[str, str]] = {}

    for paragraph, locator in _iter_located_paragraphs(docx):
        p_element = getattr(paragraph, "_p", None)
        if p_element is None:
            continue
        for node in p_element.iter():
            tag = node.tag
            if tag == qn("w:commentRangeStart"):
                comment_id = node.get(qn("w:id"))
                if comment_id is None:
                    continue
                open_ids.setdefault(comment_id, [])
                started_at.setdefault(comment_id, locator)
            elif tag == qn("w:commentRangeEnd"):
                comment_id = node.get(qn("w:id"))
                if comment_id is None or comment_id not in open_ids:
                    continue
                finished[comment_id] = (
                    started_at.get(comment_id, locator),
                    "".join(open_ids.pop(comment_id)),
                )
                started_at.pop(comment_id, None)
            elif open_ids:
                chunk = _visible_chunk(node)
                if chunk:
                    for buffer in open_ids.values():
                        buffer.append(chunk)

    for comment_id, buffer in open_ids.items():
        finished[comment_id] = (started_at.get(comment_id, ""), "".join(buffer))
    return finished


def _visible_chunk(node: Any) -> str:
    tag = node.tag
    if tag == qn("w:t"):
        return node.text or ""
    if tag == qn("w:tab"):
        return "\t"
    if tag in (qn("w:br"), qn("w:cr")):
        return "\n"
    return ""


def _iter_located_paragraphs(docx: Any) -> Iterator[tuple[Any, str]]:
    # Locator scheme matches ``parser_docx`` so a comment's locator joins to the
    # same paragraph node ``load_docx`` emits.
    paragraph_index = 0
    table_index = 0
    for block in docx.iter_inner_content():
        if isinstance(block, Paragraph):
            yield block, f"body:p:{paragraph_index}"
            paragraph_index += 1
        elif isinstance(block, Table):
            yield from _iter_table_paragraphs(block, table_index)
            table_index += 1
    for section_index, section in enumerate(getattr(docx, "sections", [])):
        for paragraph_index, paragraph in enumerate(section.header.paragraphs):
            yield paragraph, f"header:{section_index}:p:{paragraph_index}"
        for paragraph_index, paragraph in enumerate(section.footer.paragraphs):
            yield paragraph, f"footer:{section_index}:p:{paragraph_index}"


def _iter_table_paragraphs(table: Table, table_index: int) -> Iterator[tuple[Any, str]]:
    seen_cells: set[object] = set()
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            if cell._tc in seen_cells:
                continue
            seen_cells.add(cell._tc)
            for paragraph_index, paragraph in enumerate(cell.paragraphs):
                locator = (
                    f"table:{table_index}:row:{row_index}:cell:{cell_index}:p:{paragraph_index}"
                )
                yield paragraph, locator


def _comment_parent_ids(path: str | Path) -> dict[str, str]:
    """Map reply comment id -> parent comment id from commentsExtended.xml."""
    try:
        with ZipFile(str(path)) as bundle:
            names = set(bundle.namelist())
            if _COMMENTS_PART not in names or _COMMENTS_EXTENDED_PART not in names:
                return {}
            comments_xml = bundle.read(_COMMENTS_PART)
            extended_xml = bundle.read(_COMMENTS_EXTENDED_PART)
    except (OSError, BadZipFile, KeyError):
        return {}

    para_to_comment = _comment_ids_by_para_id(comments_xml)
    if not para_to_comment:
        return {}
    try:
        root = etree.fromstring(extended_xml)
    except etree.XMLSyntaxError:
        return {}

    parents: dict[str, str] = {}
    for element in root.iter(f"{{{_W15_NS}}}commentEx"):
        para_id = element.get(f"{{{_W15_NS}}}paraId")
        parent_para = element.get(f"{{{_W15_NS}}}paraIdParent")
        if not para_id or not parent_para:
            continue
        comment_id = para_to_comment.get(para_id)
        parent_id = para_to_comment.get(parent_para)
        if comment_id and parent_id and comment_id != parent_id:
            parents[comment_id] = parent_id
    return parents


def _comment_ids_by_para_id(comments_xml: bytes) -> dict[str, str]:
    try:
        root = etree.fromstring(comments_xml)
    except etree.XMLSyntaxError:
        return {}
    mapping: dict[str, str] = {}
    for comment in root.findall(f"{{{_W_NS}}}comment"):
        comment_id = comment.get(f"{{{_W_NS}}}id")
        if comment_id is None:
            continue
        for paragraph in comment.findall(f"{{{_W_NS}}}p"):
            para_id = paragraph.get(f"{{{_W14_NS}}}paraId")
            if para_id:
                mapping[para_id] = comment_id
                break
    return mapping


def _merge_content_type_overrides(
    rendered: bytes, source: bytes, missing_parts: dict[str, bytes]
) -> bytes:
    if not source:
        return rendered
    rendered_root = etree.fromstring(rendered)
    source_root = etree.fromstring(source)
    have = {
        override.get("PartName")
        for override in rendered_root.findall(f"{{{_CT_NS}}}Override")
    }
    wanted = {"/" + name if not name.startswith("/") else name for name in missing_parts}
    changed = False
    for override in source_root.findall(f"{{{_CT_NS}}}Override"):
        part_name = override.get("PartName")
        if part_name in wanted and part_name not in have:
            rendered_root.append(_copy_element(override))
            have.add(part_name)
            changed = True
    return etree.tostring(rendered_root, xml_declaration=True, encoding="UTF-8") if changed else rendered


def _merge_document_relationships(
    rendered: bytes, source: bytes, missing_parts: dict[str, bytes]
) -> bytes:
    if not source:
        return rendered
    rendered_root = etree.fromstring(rendered)
    source_root = etree.fromstring(source)
    have_targets = {
        rel.get("Target")
        for rel in rendered_root.findall(f"{{{_REL_NS}}}Relationship")
    }
    used_ids = {
        rel.get("Id") for rel in rendered_root.findall(f"{{{_REL_NS}}}Relationship")
    }
    wanted_targets = {
        name.split("/")[-1] for name in missing_parts if name.startswith("word/")
    }
    next_id = 1
    changed = False
    for rel in source_root.findall(f"{{{_REL_NS}}}Relationship"):
        target = rel.get("Target")
        if target not in _THREAD_REL_TARGETS and target not in wanted_targets:
            continue
        if target in have_targets:
            continue
        while f"rId{next_id}" in used_ids:
            next_id += 1
        rel.set("Id", f"rId{next_id}")
        used_ids.add(f"rId{next_id}")
        next_id += 1
        rendered_root.append(_copy_element(rel))
        have_targets.add(target)
        changed = True
    return etree.tostring(rendered_root, xml_declaration=True, encoding="UTF-8") if changed else rendered


def _copy_element(element: Any) -> Any:
    return etree.fromstring(etree.tostring(element))

"""Word comment read API: structured comments with body anchors.

Existing Word comments are review input. Mechanical identity, range anchors,
and thread metadata come from ``docxtor.AddressableComment``. This module
projects that record into ReviewKit's public ``DocxComment`` and keeps the
review-coverage checks (ambiguous ids, incomplete markers, unresolved
locators). It does not fork Word comment markup or restore thread sidecars;
Docxtor already restores those on write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx.opc.exceptions import PackageNotFoundError
from docxtor import AddressableComment, DocxDocument as AddressableDocxDocument
from lxml import etree

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
_W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"

_COMMENTS_PART = "word/comments.xml"
_COMMENTS_EXTENDED_PART = "word/commentsExtended.xml"
_COMMENT_MARKER_NAMES = frozenset(
    {"commentRangeStart", "commentRangeEnd", "commentReference"}
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

    Identity, text, locator, anchor text, and parent/reply links are a
    projection of ``docxtor.AddressableComment``. Returns an empty list when
    the package carries no comments or cannot be opened as a package.
    """
    try:
        document = AddressableDocxDocument.open(path)
    except (OSError, ValueError, PackageNotFoundError, BadZipFile):
        return []
    return comments_from_document(document)


def comments_from_document(document: AddressableDocxDocument) -> list[DocxComment]:
    """Project Docxtor mechanical comments into ReviewKit's public records."""
    return [_project_comment(comment) for comment in document.comments]


def comments_for_locator(
    comments: list[DocxComment], locator: str | None
) -> list[DocxComment]:
    """Comments whose range starts in the paragraph identified by ``locator``."""
    if not locator:
        return []
    return [comment for comment in comments if comment.locator == locator]


def _project_comment(comment: AddressableComment) -> DocxComment:
    return DocxComment(
        id=comment.comment_id,
        author=comment.author or "",
        initials=comment.initials or "",
        text=comment.text,
        locator=comment.locator,
        anchor_text=comment.anchor_text,
        parent_id=comment.parent_id,
    )


def _comment_markers_are_complete(path: str | Path, comments: list[DocxComment]) -> bool:
    """Return whether every source comment marker has one unambiguous body."""
    body_ids = [comment.id for comment in comments]
    if len(set(body_ids)) != len(body_ids):
        return False
    marker_counts: dict[str, dict[str, int]] = {}
    try:
        with ZipFile(str(path)) as bundle:
            for name in bundle.namelist():
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                root = etree.fromstring(bundle.read(name))
                for element in root.iter():
                    if not isinstance(element.tag, str):
                        continue
                    qualified = etree.QName(element)
                    if qualified.namespace != _W_NS or qualified.localname not in _COMMENT_MARKER_NAMES:
                        continue
                    marker_id = element.get(f"{{{_W_NS}}}id")
                    if marker_id is None:
                        return False
                    counts = marker_counts.setdefault(
                        marker_id,
                        {"commentRangeStart": 0, "commentRangeEnd": 0, "commentReference": 0},
                    )
                    counts[qualified.localname] += 1
    except (OSError, BadZipFile, KeyError, etree.XMLSyntaxError):
        return False

    body_id_set = set(body_ids)
    if any(marker_id not in body_id_set for marker_id in marker_counts):
        return False
    for counts in marker_counts.values():
        if any(counts[name] != 1 for name in _COMMENT_MARKER_NAMES):
            return False
    return True


def _comment_thread_ids_are_complete(path: str | Path) -> bool:
    """Return whether comment-thread paragraph IDs are unique and resolvable."""
    try:
        with ZipFile(str(path)) as bundle:
            names = set(bundle.namelist())
            if _COMMENTS_PART not in names:
                return True
            comments_xml = bundle.read(_COMMENTS_PART)
            extended_xml = (
                bundle.read(_COMMENTS_EXTENDED_PART)
                if _COMMENTS_EXTENDED_PART in names
                else None
            )
    except (OSError, BadZipFile, KeyError):
        return False

    try:
        comments_root = etree.fromstring(comments_xml)
    except etree.XMLSyntaxError:
        return False
    para_ids = [
        paragraph.get(f"{{{_W14_NS}}}paraId")
        for paragraph in comments_root.iter(f"{{{_W_NS}}}p")
        if paragraph.get(f"{{{_W14_NS}}}paraId") is not None
    ]
    if len(set(para_ids)) != len(para_ids):
        return False
    if extended_xml is None:
        return True
    try:
        extended_root = etree.fromstring(extended_xml)
    except etree.XMLSyntaxError:
        return False
    known_para_ids = set(para_ids)
    seen_para_ids: set[str] = set()
    for element in extended_root.iter(f"{{{_W15_NS}}}commentEx"):
        para_id = element.get(f"{{{_W15_NS}}}paraId")
        parent_id = element.get(f"{{{_W15_NS}}}paraIdParent")
        if para_id in seen_para_ids:
            return False
        if para_id is not None:
            seen_para_ids.add(para_id)
        if para_id not in known_para_ids or (
            parent_id is not None and parent_id not in known_para_ids
        ):
            return False
    return True

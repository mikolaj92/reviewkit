from __future__ import annotations

import re

from lxml import etree

_COMMENT_PART_PREFIXES = ("word/comments", "word/people.xml")
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
COMMENT_ANCHOR_RE = re.compile(rb"<w:comment(Reference|RangeStart|RangeEnd)(?=[\s>/])")
_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def serialize(root: etree._Element) -> bytes:
    return (_XML_DECLARATION + etree.tostring(root, encoding="unicode")).encode()


def is_comment_part(name: str) -> bool:
    return name.startswith(_COMMENT_PART_PREFIXES)


def strip_comment_anchors(root: etree._Element, word_namespace: str) -> None:
    def tag(name: str) -> str:
        return f"{{{word_namespace}}}{name}"

    for element in list(root.iter(tag("commentRangeStart"), tag("commentRangeEnd"))):
        _remove(element)
    for element in list(root.iter(tag("commentReference"))):
        run = element.getparent()
        _remove(run if run is not None and run.tag == tag("r") else element)


def strip_comment_relationships(data: bytes) -> bytes:
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
    return serialize(root) if changed else data


def strip_comment_content_types(data: bytes) -> bytes:
    root = etree.fromstring(data)
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

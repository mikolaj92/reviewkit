from __future__ import annotations

import re

from lxml import etree

_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.)])?")
_RANGE_REVISION_PAIRS = (
    ("moveFromRangeStart", "moveFromRangeEnd", "moveFrom"),
    ("moveToRangeStart", "moveToRangeEnd", "moveTo"),
    ("customXmlDelRangeStart", "customXmlDelRangeEnd", None),
    ("customXmlInsRangeStart", "customXmlInsRangeEnd", None),
    ("customXmlMoveFromRangeStart", "customXmlMoveFromRangeEnd", None),
    ("customXmlMoveToRangeStart", "customXmlMoveToRangeEnd", None),
)


def paragraph_for_mark(mark: etree._Element, word_namespace: str) -> etree._Element | None:
    properties = mark.getparent()
    paragraph_properties = properties.getparent() if properties is not None else None
    paragraph = paragraph_properties.getparent() if paragraph_properties is not None else None
    if paragraph is None or paragraph.tag != _tag(word_namespace, "p"):
        return None
    return paragraph


def merge_paragraph_into_next(mark: etree._Element, word_namespace: str) -> bool:
    paragraph = paragraph_for_mark(mark, word_namespace)
    if paragraph is None:
        return False
    current_block = _paragraph_block(paragraph, word_namespace)
    next_paragraph = _next_paragraph(current_block, word_namespace)
    if next_paragraph is None:
        return False
    insert_at = (
        1 if len(next_paragraph) and next_paragraph[0].tag == _tag(word_namespace, "pPr") else 0
    )
    for child in [node for node in paragraph if node.tag != _tag(word_namespace, "pPr")]:
        next_paragraph.insert(insert_at, child)
        insert_at += 1
    parent = current_block.getparent()
    if parent is None:
        return False
    parent.remove(current_block)
    return True


def remove_paragraph_block(paragraph: etree._Element, word_namespace: str) -> bool:
    block = _paragraph_block(paragraph, word_namespace)
    parent = block.getparent()
    if parent is None:
        return False
    parent.remove(block)
    return True


def is_content_control_paragraph(mark: etree._Element, word_namespace: str) -> bool:
    paragraph = paragraph_for_mark(mark, word_namespace)
    return paragraph is not None and _paragraph_block(paragraph, word_namespace) is not paragraph


def drop_inserted_numbering_leftover(
    paragraph: etree._Element,
    word_namespace: str,
    *,
    drop_comments: bool,
) -> bool:
    if paragraph.getparent() is None:
        return False
    text = "".join(
        node.text or ""
        for node in paragraph.iter(
            _tag(word_namespace, "t"),
            _tag(word_namespace, "delText"),
        )
    ).strip()
    properties = paragraph.find(_tag(word_namespace, "pPr"))
    numbered = (
        properties is not None
        and properties.find(_tag(word_namespace, "numPr")) is not None
    )
    # Word may leave a manually typed list token outside ``w:ins`` while tracking
    # the new point's text. Its presence in this exact insertion-owning paragraph
    # is the provenance that links the otherwise bare token to the rejected point.
    if not ((numbered and not text) or _NUMBER_TOKEN_RE.fullmatch(text)):
        return False
    if any(
        next(paragraph.iter(_tag(word_namespace, name)), None) is not None
        for name in ("tab", "br", "cr", "drawing", "object", "pict", "fldChar", "sym")
    ):
        return False
    if not drop_comments and any(
        next(paragraph.iter(_tag(word_namespace, name)), None) is not None
        for name in ("commentRangeStart", "commentRangeEnd", "commentReference")
    ):
        return False
    return remove_paragraph_block(paragraph, word_namespace)


def drop_paired_range_revision_markers(
    root: etree._Element,
    word_namespace: str,
) -> str | None:
    markers: list[etree._Element] = []
    for start_name, end_name, required_wrapper in _RANGE_REVISION_PAIRS:
        starts = list(root.iter(_tag(word_namespace, start_name)))
        ends = list(root.iter(_tag(word_namespace, end_name)))
        if not starts and not ends:
            continue
        start_ids = [element.get(_tag(word_namespace, "id")) for element in starts]
        end_ids = [element.get(_tag(word_namespace, "id")) for element in ends]
        if (
            None in start_ids
            or None in end_ids
            or len(start_ids) != len(set(start_ids))
            or set(start_ids) != set(end_ids)
            or (
                required_wrapper is not None
                and next(root.iter(_tag(word_namespace, required_wrapper)), None) is None
            )
        ):
            return start_name
        markers.extend((*starts, *ends))
    for marker in markers:
        _remove_element(marker)
    return None


def _paragraph_block(paragraph: etree._Element, word_namespace: str) -> etree._Element:
    content = paragraph.getparent()
    control = content.getparent() if content is not None else None
    if (
        content is not None
        and content.tag == _tag(word_namespace, "sdtContent")
        and control is not None
        and control.tag == _tag(word_namespace, "sdt")
        and len(content) == 1
    ):
        return control
    return paragraph


def _next_paragraph(block: etree._Element, word_namespace: str) -> etree._Element | None:
    candidate = block.getnext()
    if candidate is None:
        return None
    if candidate.tag == _tag(word_namespace, "p"):
        return candidate
    if candidate.tag != _tag(word_namespace, "sdt"):
        return None
    content = candidate.find(_tag(word_namespace, "sdtContent"))
    if content is None or len(content) != 1:
        return None
    paragraph = content[0]
    return paragraph if paragraph.tag == _tag(word_namespace, "p") else None


def _tag(word_namespace: str, name: str) -> str:
    return f"{{{word_namespace}}}{name}"


def _remove_element(element: etree._Element) -> None:
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

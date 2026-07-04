"""Body-anchor grammar and body-only paragraph resolution for DOCX documents.

The supported insertion-anchor grammar is ``body:p:<digits>`` and
``body:p:last``. Numeric indices are body-local positions in
``document.paragraphs``; anything outside the body fails closed instead of
resolving into tables, headers, or footers. Insertion, validation, and any
caller-side planning should share these helpers so the grammar cannot drift
between pipeline stages.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from docx.document import Document as DocxDocument
from docx.oxml.text.paragraph import CT_P
from docx.text.paragraph import Paragraph

ANCHOR_LAST = "body:p:last"

# Signature/closing-section markers are only meaningful in the document tail:
# only paragraphs within the last _SIGNATURE_TAIL_WINDOW non-empty body
# paragraphs may start a signature block.
_SIGNATURE_TAIL_WINDOW = 5


def find_signature_block_start(
    document: DocxDocument,
    ignore_texts: Sequence[str] = (),
    *,
    signature_patterns: Sequence[re.Pattern[str]] = (),
) -> CT_P | None:
    """Return the body element starting the trailing signature block, or ``None``.

    ``signature_patterns`` are caller-supplied compiled regexes matched against
    lower-cased paragraph text (match on word boundaries in the pattern itself
    so e.g. ``date`` does not match inside ``update``). With no patterns there
    is no signature detection and the scan returns ``None``.

    Insertion and validation should share one scan so insertion bounds and any
    post-insertion placement gate cannot drift apart. Paragraphs whose text
    contains any of ``ignore_texts`` (already-inserted clauses) are treated
    like whitespace: they neither start the block nor end the bottom-up scan,
    so a clause inserted into the tail cannot split the signature block.
    """
    body = document.element.body
    children = list(body.iterchildren())
    lowered_ignores = [ignored.lower() for ignored in ignore_texts if ignored]

    block_start_index = len(children)
    scanned_without_match = 0
    for i in range(len(children) - 1, -1, -1):
        element = children[i]
        # Comment/PI nodes expose a callable .tag, not a string (lxml).
        if not isinstance(element.tag, str) or not element.tag.endswith("}p"):
            continue
        text_content = " ".join(element.itertext()).lower()
        if not text_content.strip():
            # Whitespace-only paragraphs neither start a signature block
            # nor consume the tail window.
            continue
        if any(ignored in text_content for ignored in lowered_ignores):
            continue
        if any(pattern.search(text_content) for pattern in signature_patterns):
            block_start_index = i
        elif block_start_index < len(children):
            # First non-matching paragraph above the signature block ends the scan.
            break
        else:
            scanned_without_match += 1
            if scanned_without_match >= _SIGNATURE_TAIL_WINDOW:
                # No signature block starts within the tail window.
                break

    if block_start_index < len(children):
        return children[block_start_index]
    return None


def parse_body_anchor_index(anchor: str) -> int | None:
    """Return the body-paragraph index for ``body:p:<digits>`` anchors, else ``None``."""
    parts = anchor.split(":")
    if len(parts) == 3 and parts[0] == "body" and parts[1] == "p" and parts[2].isdigit():
        return int(parts[2])
    return None


def is_supported_anchor(anchor: str) -> bool:
    """True when the anchor uses the grammar the insertion engine can actually consume."""
    return anchor == ANCHOR_LAST or parse_body_anchor_index(anchor) is not None


def find_body_paragraph(document: DocxDocument, index: int) -> Paragraph | None:
    """Resolve a body-local paragraph index; ``None`` outside the body (fail closed)."""
    paragraphs = document.paragraphs
    if 0 <= index < len(paragraphs):
        return paragraphs[index]
    return None


def find_paragraph_by_locator(document: DocxDocument, locator: str | None) -> Paragraph | None:
    """Resolve a parser locator (``body|table|header|footer ...:p:<n>``) to its paragraph.

    Locator indices are local to their section, matching the segment ids the
    DOCX parser emits. Unknown or out-of-range locators return ``None``; the
    grammar is strict (digits only, no trailing tokens), so malformed locators
    fail closed instead of resolving to a nearby paragraph.
    """
    if not locator:
        return None
    parts = locator.split(":")
    if len(parts) < 3 or parts[-2] != "p" or not parts[-1].isdigit():
        return None
    index = int(parts[-1])
    prefix = parts[:-2]

    paragraphs: list[Paragraph] | None = None
    if prefix == ["body"]:
        paragraphs = list(document.paragraphs)
    elif (
        len(prefix) == 6
        and prefix[0] == "table"
        and prefix[2] == "row"
        and prefix[4] == "cell"
        and prefix[1].isdigit()
        and prefix[3].isdigit()
        and prefix[5].isdigit()
    ):
        table_index, row_index, cell_index = int(prefix[1]), int(prefix[3]), int(prefix[5])
        if table_index < len(document.tables):
            table = document.tables[table_index]
            if row_index < len(table.rows):
                row = table.rows[row_index]
                if cell_index < len(row.cells):
                    paragraphs = list(row.cells[cell_index].paragraphs)
    elif len(prefix) == 2 and prefix[0] in ("header", "footer") and prefix[1].isdigit():
        section_index = int(prefix[1])
        if section_index < len(document.sections):
            section = document.sections[section_index]
            part = section.header if prefix[0] == "header" else section.footer
            paragraphs = list(part.paragraphs)

    if paragraphs is None or not 0 <= index < len(paragraphs):
        return None
    return paragraphs[index]

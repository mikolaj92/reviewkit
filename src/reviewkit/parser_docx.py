"""DOCX parser that builds the internal review hierarchy."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from zipfile import ZipFile

from docx import Document as DocxDocument

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]*", re.UNICODE)
_REVISION_TAG_RE = re.compile(rb"<w:(ins|del)(?=[\s>/])")


def load_docx(path: str | Path) -> ReviewDocument:
    source_path = Path(path)
    docx = DocxDocument(str(source_path))

    sections: list[SectionNode] = []
    current = SectionNode(id="s1")
    next_section_number = 2
    next_paragraph_number = 1

    for docx_paragraph, locator, source in _iter_paragraph_sources(docx):
        text = str(getattr(docx_paragraph, "text", "")).strip()
        if not text:
            continue

        if _is_heading(docx_paragraph):
            if current.title or current.paragraphs:
                sections.append(current)
                current = SectionNode(
                    id=f"s{next_section_number}",
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                )
                next_section_number += 1
            else:
                current = SectionNode(
                    id=current.id,
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                )
            continue

        paragraph_id = f"p{next_paragraph_number}"
        next_paragraph_number += 1
        sentences = [
            SentenceNode(
                id=f"{paragraph_id}.s{index}",
                text=sentence,
                paragraph_id=paragraph_id,
                char_start=start,
                char_end=end,
                locator=f"{locator}:s:{index - 1}",
                metadata={"source": source},
            )
            for index, (sentence, start, end) in enumerate(
                split_sentences_with_spans(text), start=1
            )
        ]
        current.paragraphs.append(
            ParagraphNode(
                id=paragraph_id,
                text=text,
                section_id=current.id,
                locator=locator,
                metadata={"source": source},
                sentences=sentences,
            )
        )

    if current.title or current.paragraphs or not sections:
        sections.append(current)

    metadata = {
        "paragraph_count": str(sum(len(section.paragraphs) for section in sections)),
        "table_count": str(len(docx.tables)),
        "comment_count": str(_comment_count(docx)),
        "tracked_revisions_detected": str(_contains_tracked_revisions(source_path)).lower(),
    }
    return ReviewDocument(source_path=source_path, sections=sections, metadata=metadata)


def split_sentences(text: str) -> list[str]:
    return [sentence for sentence, _start, _end in split_sentences_with_spans(text)]


def split_sentences_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Split ``text`` into sentences, keeping each sentence's char span within ``text``.

    The returned offsets refer to the stripped sentence as it appears inside
    ``text`` so callers can rebase sentence-relative locators into paragraph
    coordinates.
    """

    spans: list[tuple[str, int, int]] = []
    for match in _SENTENCE_RE.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = match.start() + (len(raw) - len(raw.lstrip()))
        spans.append((stripped, start, start + len(stripped)))
    if spans:
        return spans
    stripped = text.strip()
    if not stripped:
        return []
    start = text.find(stripped)
    return [(stripped, start, start + len(stripped))]


def _is_heading(docx_paragraph: object) -> bool:
    style = getattr(docx_paragraph, "style", None)
    style_name = str(getattr(style, "name", "")).lower()
    return style_name.startswith("heading") or style_name.startswith("naglowek")


def _iter_paragraph_sources(docx: object) -> Iterator[tuple[object, str, str]]:
    paragraphs = getattr(docx, "paragraphs", [])
    for index, paragraph in enumerate(paragraphs):
        yield paragraph, f"body:p:{index}", "body"

    for table_index, table in enumerate(getattr(docx, "tables", [])):
        for row_index, row in enumerate(table.rows):
            for cell_index, cell in enumerate(row.cells):
                for paragraph_index, paragraph in enumerate(cell.paragraphs):
                    locator = (
                        f"table:{table_index}:row:{row_index}:cell:{cell_index}:p:{paragraph_index}"
                    )
                    yield paragraph, locator, "table"

    for section_index, section in enumerate(getattr(docx, "sections", [])):
        for paragraph_index, paragraph in enumerate(section.header.paragraphs):
            yield paragraph, f"header:{section_index}:p:{paragraph_index}", "header"
        for paragraph_index, paragraph in enumerate(section.footer.paragraphs):
            yield paragraph, f"footer:{section_index}:p:{paragraph_index}", "footer"


def _comment_count(docx: object) -> int:
    comments = getattr(docx, "comments", None)
    if comments is None:
        return 0
    return sum(1 for _ in comments)


def _contains_tracked_revisions(path: Path) -> bool:
    try:
        with ZipFile(path) as archive:
            for member in archive.namelist():
                if not member.startswith("word/") or not member.endswith(".xml"):
                    continue
                if Path(member).name not in {"document.xml", "comments.xml", "footnotes.xml"}:
                    continue
                if _REVISION_TAG_RE.search(archive.read(member)):
                    return True
    except OSError:
        return False
    return False

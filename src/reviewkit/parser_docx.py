"""DOCX parser that builds the internal review hierarchy."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from zipfile import ZipFile

from docx import Document as DocxDocument

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode

_SENTENCE_PUNCT_RE = re.compile(r"[.!?]+", re.UNICODE)
_TRAILING_WORD_RE = re.compile(r"(\w+)$", re.UNICODE)
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
    segment_start = 0
    for match in _SENTENCE_PUNCT_RE.finditer(text):
        if not _is_sentence_boundary(text, match.start(), match.end()):
            continue
        _append_span(spans, text, segment_start, match.end())
        segment_start = match.end()
    _append_span(spans, text, segment_start, len(text))
    if spans:
        return spans
    stripped = text.strip()
    if not stripped:
        return []
    start = text.find(stripped)
    return [(stripped, start, start + len(stripped))]


def _append_span(
    spans: list[tuple[str, int, int]], text: str, start: int, end: int
) -> None:
    segment = text[start:end]
    stripped = segment.strip()
    if not stripped:
        return
    lead = len(segment) - len(segment.lstrip())
    span_start = start + lead
    spans.append((stripped, span_start, span_start + len(stripped)))


def _is_sentence_boundary(text: str, punct_start: int, punct_end: int) -> bool:
    """Decide whether the punctuation run at ``[punct_start:punct_end]`` ends a sentence.

    Language- and domain-neutral heuristics avoid the classic over-splits:
    - a boundary must be followed by whitespace or end-of-text, so ``3.14`` and the
      inner dots of ``o.o.`` are never boundaries;
    - a period preceded by a single-letter token is treated as an initial/abbreviation
      (``J. R. R.``, the trailing ``o.``);
    - a period followed by a lowercase word is treated as an abbreviation (``Sp. z``).
    ``!`` and ``?`` are always strong boundaries when followed by whitespace/end.
    """
    if punct_end < len(text) and not text[punct_end].isspace():
        return False
    if "!" in text[punct_start:punct_end] or "?" in text[punct_start:punct_end]:
        return True
    trailing = _TRAILING_WORD_RE.search(text[:punct_start])
    if trailing is not None and len(trailing.group(1)) == 1 and trailing.group(1).isalpha():
        return False
    following = _next_non_space_char(text, punct_end)
    if following and following.islower():
        return False
    return True


def _next_non_space_char(text: str, index: int) -> str:
    while index < len(text) and text[index].isspace():
        index += 1
    return text[index] if index < len(text) else ""


def _is_heading(docx_paragraph: object) -> bool:
    style = getattr(docx_paragraph, "style", None)
    if style is None:
        return False
    # ``style_id`` is the language-independent internal identifier Word assigns to
    # built-in styles ("Heading1", "Heading2", "Title", ...), so heading detection
    # stays domain- and language-agnostic regardless of the document's UI language.
    style_id = str(getattr(style, "style_id", "") or "")
    if style_id.startswith("Heading") or style_id == "Title":
        return True
    # python-docx exposes built-in style names in canonical English ("heading 1"),
    # so a name-based fallback remains language-neutral for built-in styles.
    style_name = str(getattr(style, "name", "") or "").lower()
    return style_name.startswith("heading") or style_name.startswith("title")


def _iter_paragraph_sources(docx: object) -> Iterator[tuple[object, str, str]]:
    paragraphs = getattr(docx, "paragraphs", [])
    for index, paragraph in enumerate(paragraphs):
        yield paragraph, f"body:p:{index}", "body"

    for table_index, table in enumerate(getattr(docx, "tables", [])):
        # A merged cell is yielded by ``row.cells`` once per grid position it spans
        # (across columns AND rows), so walk each underlying ``<w:tc>`` exactly once at
        # its first grid position - otherwise merged cells (ubiquitous in forms and
        # contracts) are reviewed twice, edited twice, and inflate paragraph_count.
        # The set holds the lxml element proxies (not ``id()``, whose value is reused
        # after GC) so identity is stable and unique per physical cell.
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
    # Scan every content part under ``word/`` (document, comments, footnotes/endnotes,
    # AND headers/footers), not a fixed allowlist: a tracked change living only in a
    # header or footer must still surface so the pipeline can warn the human. ``w:ins``/
    # ``w:del`` only appear in revised content, so this cannot false-positive on the
    # ``w:trackChanges`` *setting* in settings.xml.
    try:
        with ZipFile(path) as archive:
            for member in archive.namelist():
                if not member.startswith("word/") or not member.endswith(".xml"):
                    continue
                if _REVISION_TAG_RE.search(archive.read(member)):
                    return True
    except OSError:
        return False
    return False

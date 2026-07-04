"""DOCX parser that builds the internal review hierarchy."""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterator
from pathlib import Path
from zipfile import ZipFile

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode

# Terminators span Latin (. ! ?) and common non-Latin sentence enders so the sentence
# tier does not silently disappear for non-Latin-script documents: CJK (。！？), the
# horizontal ellipsis (…), the Arabic question mark (؟) and the Devanagari danda (।).
_SENTENCE_PUNCT_RE = re.compile(r"[.!?。！？…؟।]+", re.UNICODE)
# The non-Latin enders above are unambiguous, script-specific sentence terminators with
# no abbreviation/decimal role, and CJK writes no space between sentences - so they end a
# sentence regardless of what follows, unlike the whitespace-gated Latin punctuation.
_STRONG_TERMINATORS = frozenset("。！？…؟।")
_TRAILING_WORD_RE = re.compile(r"(\w+)$", re.UNICODE)
_REVISION_TAG_RE = re.compile(rb"<w:(ins|del)(?=[\s>/])")


def load_docx(path: str | Path) -> ReviewDocument:
    source_path = Path(path)
    docx = DocxDocument(str(source_path))

    # Section/paragraph id counters are shared across the body walk and the synthetic
    # header/footer sections so every node keeps a globally unique id. "s1" is reserved
    # for the implicit leading body section, so section numbering starts at 2.
    section_ids = itertools.count(2)
    paragraph_ids = itertools.count(1)

    sections: list[SectionNode] = []
    current = SectionNode(id="s1")

    # Walk the body in true document order so a table interleaves with the paragraphs
    # around it and lands under its authoring heading, instead of every table being
    # appended to whatever section happened to be open at the end of the body.
    for docx_paragraph, locator, source in _iter_body_sources(docx):
        text = str(getattr(docx_paragraph, "text", "")).strip()
        if not text:
            continue

        if _is_heading(docx_paragraph):
            if current.title or current.paragraphs:
                sections.append(current)
                current = SectionNode(
                    id=f"s{next(section_ids)}",
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                )
            else:
                current = SectionNode(
                    id=current.id,
                    title=text,
                    locator=locator,
                    metadata={"source": source},
                )
            continue

        current.paragraphs.append(
            _paragraph_node(f"p{next(paragraph_ids)}", text, current.id, locator, source)
        )

    if current.title or current.paragraphs or not sections:
        sections.append(current)

    # Header/footer paragraphs get their own synthetic sections keyed by source so they
    # are not misread as body prose tacked onto the trailing body section. Locator strings
    # ("header:S:p:P"/"footer:S:p:P") are unchanged, so rendering resolves them identically.
    sections.extend(_header_footer_sections(docx, section_ids, paragraph_ids))

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
    - non-Latin terminators (``。！？…؟।``) are unambiguous sentence enders with no
      abbreviation role, and CJK writes no inter-sentence space, so a run containing one
      is always a boundary regardless of the following character;
    - otherwise (Latin ``.!?``) a boundary must be followed by whitespace or end-of-text,
      so ``3.14`` and the inner dots of ``o.o.`` are never boundaries;
    - a period preceded by a single-letter token is treated as an initial/abbreviation
      (``J. R. R.``, the trailing ``o.``);
    - a period followed by a lowercase word is treated as an abbreviation (``Sp. z``).
    ``!`` and ``?`` are always strong boundaries when followed by whitespace/end.
    """
    if any(char in _STRONG_TERMINATORS for char in text[punct_start:punct_end]):
        return True
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


def _paragraph_node(
    paragraph_id: str, text: str, section_id: str, locator: str, source: str
) -> ParagraphNode:
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
        for index, (sentence, start, end) in enumerate(split_sentences_with_spans(text), start=1)
    ]
    return ParagraphNode(
        id=paragraph_id,
        text=text,
        section_id=section_id,
        locator=locator,
        metadata={"source": source},
        sentences=sentences,
    )


def _iter_body_sources(docx: object) -> Iterator[tuple[object, str, str]]:
    # ``iter_inner_content`` yields body ``<w:p>`` and ``<w:tbl>`` children in true document
    # order, so a table is emitted at its real position (between the paragraphs that surround
    # it) rather than after all paragraphs. Separate paragraph/table counters keep the emitted
    # locators identical to the previous scheme: ``paragraph_index`` matches ``docx.paragraphs``
    # (which excludes table paragraphs) and ``table_index`` matches ``docx.tables``.
    paragraph_index = 0
    table_index = 0
    for block in docx.iter_inner_content():  # type: ignore[attr-defined]
        if isinstance(block, Paragraph):
            yield block, f"body:p:{paragraph_index}", "body"
            paragraph_index += 1
        elif isinstance(block, Table):
            yield from _iter_table_sources(block, table_index)
            table_index += 1


def _iter_table_sources(table: Table, table_index: int) -> Iterator[tuple[object, str, str]]:
    # A merged cell is yielded by ``row.cells`` once per grid position it spans (across
    # columns AND rows), so walk each underlying ``<w:tc>`` exactly once at its first grid
    # position - otherwise merged cells (ubiquitous in forms and contracts) are reviewed
    # twice, edited twice, and inflate paragraph_count. The set holds the lxml element
    # proxies (not ``id()``, whose value is reused after GC) so identity is stable and
    # unique per physical cell.
    seen_cells: set[object] = set()
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            if cell._tc in seen_cells:
                continue
            seen_cells.add(cell._tc)
            for paragraph_index, paragraph in enumerate(cell.paragraphs):
                locator = f"table:{table_index}:row:{row_index}:cell:{cell_index}:p:{paragraph_index}"
                yield paragraph, locator, "table"


def _header_footer_sections(
    docx: object, section_ids: Iterator[int], paragraph_ids: Iterator[int]
) -> list[SectionNode]:
    grouped: dict[str, list[tuple[object, str]]] = {}
    for docx_paragraph, locator, source in _iter_header_footer_sources(docx):
        grouped.setdefault(source, []).append((docx_paragraph, locator))

    sections: list[SectionNode] = []
    for source, entries in grouped.items():
        non_empty = [
            (paragraph, locator)
            for paragraph, locator in entries
            if str(getattr(paragraph, "text", "")).strip()
        ]
        if not non_empty:
            continue
        section_id = f"s{next(section_ids)}"
        paragraphs = [
            _paragraph_node(
                f"p{next(paragraph_ids)}",
                str(getattr(paragraph, "text", "")).strip(),
                section_id,
                locator,
                source,
            )
            for paragraph, locator in non_empty
        ]
        sections.append(
            SectionNode(
                id=section_id,
                # No fabricated title: capitalizing the source ("Header"/"Footer") injected an
                # English word into the reviewable tree, which the LLM would see as document
                # prose -- a language leak in the language-blind core. The header/footer
                # distinction is preserved in metadata["source"] below.
                title=None,
                metadata={"source": source},
                paragraphs=paragraphs,
            )
        )
    return sections


def _iter_header_footer_sources(docx: object) -> Iterator[tuple[object, str, str]]:
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

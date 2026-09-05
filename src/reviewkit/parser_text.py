"""Minimal plain-text and Markdown adapter for the canonical review tree."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode

_SENTENCE_PUNCT_RE = re.compile(r"[.!?。！？…؟।]+", re.UNICODE)
_STRONG_TERMINATORS = frozenset("。！？…؟।")
_TRAILING_WORD_RE = re.compile(r"(\w+)$", re.UNICODE)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class TextDocumentParser:
    """Parse a Unicode string; ATX headings form Markdown sections."""

    source_name: str | None = None

    def parse(self, source: str) -> ReviewDocument:
        return parse_text(source, source_name=self.source_name)


def parse_text(source: str, *, source_name: str | None = None) -> ReviewDocument:
    """Build a deterministic sentence → paragraph → section → document tree."""
    sections: list[SectionNode] = []
    current_title: str | None = None
    current_paragraphs: list[ParagraphNode] = []
    paragraph_count = 0
    saw_heading = False

    def finish_section() -> None:
        nonlocal current_paragraphs
        if current_title is None and not current_paragraphs and sections:
            return
        section_index = len(sections)
        section_id = f"s{section_index + 1}"
        for paragraph in current_paragraphs:
            paragraph.section_id = section_id
        sections.append(
            SectionNode(
                id=section_id,
                title=current_title,
                locator=f"text:section:{section_index}",
                metadata={"source": "text"},
                paragraphs=current_paragraphs,
            )
        )
        current_paragraphs = []

    blocks: list[str] = []
    prose: list[str] = []
    for line in source.splitlines():
        if not line.strip():
            if prose:
                blocks.append("\n".join(prose))
                prose = []
            continue
        if _HEADING_RE.fullmatch(line):
            if prose:
                blocks.append("\n".join(prose))
                prose = []
            blocks.append(line)
        else:
            prose.append(line)
    if prose:
        blocks.append("\n".join(prose))

    for block in blocks:
        heading = _HEADING_RE.fullmatch(block)
        if heading:
            saw_heading = True
            if current_title is not None or current_paragraphs:
                finish_section()
            current_title = heading.group(1).strip()
            continue
        paragraph_count += 1
        text = block.strip()
        locator = f"text:paragraph:{paragraph_count - 1}"
        sentences = [
            SentenceNode(
                id=f"p{paragraph_count}.s{index}",
                text=sentence,
                paragraph_id=f"p{paragraph_count}",
                char_start=start,
                char_end=end,
                locator=f"{locator}:sentence:{index - 1}",
                metadata={"source": "text"},
            )
            for index, (sentence, start, end) in enumerate(
                split_sentences_with_spans(text), start=1
            )
        ]
        current_paragraphs.append(
            ParagraphNode(
                id=f"p{paragraph_count}",
                text=text,
                section_id="",
                locator=locator,
                metadata={"source": "text"},
                sentences=sentences,
            )
        )

    if current_title is not None or current_paragraphs or not sections:
        finish_section()
    metadata = {
        "source_format": "markdown" if saw_heading else "text",
        "paragraph_count": str(paragraph_count),
    }
    if source_name is not None:
        metadata["source_name"] = source_name
    return ReviewDocument(sections=sections, metadata=metadata)


def split_sentences(text: str) -> list[str]:
    return [sentence for sentence, _start, _end in split_sentences_with_spans(text)]


def split_sentences_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Split text while preserving paragraph-relative character coordinates."""
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


def _append_span(spans: list[tuple[str, int, int]], text: str, start: int, end: int) -> None:
    segment = text[start:end]
    stripped = segment.strip()
    if not stripped:
        return
    lead = len(segment) - len(segment.lstrip())
    span_start = start + lead
    spans.append((stripped, span_start, span_start + len(stripped)))


def _is_sentence_boundary(text: str, punct_start: int, punct_end: int) -> bool:
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
    return not (following and following.islower())


def _next_non_space_char(text: str, index: int) -> str:
    while index < len(text) and text[index].isspace():
        index += 1
    return text[index] if index < len(text) else ""

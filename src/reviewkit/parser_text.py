"""Sentence splitter used by the DOCX walk tree."""

from __future__ import annotations

import re

_SENTENCE_PUNCT_RE = re.compile(r"[.!?。！？…؟।]+", re.UNICODE)
_STRONG_TERMINATORS = frozenset("。！？…؟।")
_TRAILING_WORD_RE = re.compile(r"(\w+)$", re.UNICODE)


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

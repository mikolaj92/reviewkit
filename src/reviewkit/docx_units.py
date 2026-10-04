"""Units of the live DOCX at each poziom.

A unit is a cut of the same file: one zdanie, one akapit, one rozdział, or
the całość. Offsets are paragraph-relative so a side effect can land on that
cut without copying the document into another file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reviewkit.comments import DocxComment, comments_for_locator
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.poziom import Poziom


@dataclass(frozen=True)
class Jednostka:
    """One unit of the file under review, as it is now."""

    poziom: Poziom
    node_id: str
    text: str
    path: Path
    locator: str | None
    char_start: int
    char_end: int
    comments: tuple[DocxComment, ...]
    visit: int
    document_pass: int


def list_units(document: ReviewDocument, poziom: Poziom, *, path: Path) -> list[Jednostka]:
    if poziom is Poziom.ZDANIE:
        units = []
        for sentence in document.iter_sentences():
            paragraph = document.paragraph_for_sentence(sentence.id)
            if paragraph is None or paragraph.locator is None:
                continue
            start, end = _sentence_span(paragraph, sentence)
            units.append(
                _unit(
                    Poziom.ZDANIE,
                    sentence.id,
                    sentence.text,
                    path,
                    paragraph.locator,
                    start,
                    end,
                    _overlapping(paragraph, document, start, end),
                )
            )
        return units
    if poziom is Poziom.AKAPIT:
        units = []
        for paragraph in document.iter_paragraphs():
            if not paragraph.locator:
                continue
            end = len(paragraph.text)
            units.append(
                _unit(
                    Poziom.AKAPIT,
                    paragraph.id,
                    paragraph.text,
                    path,
                    paragraph.locator,
                    0,
                    end,
                    tuple(comments_for_locator(document.comments, paragraph.locator)),
                )
            )
        return units
    if poziom is Poziom.ROZDZIAL:
        return [_section_unit(document, section, path) for section in document.sections]
    return [_document_unit(document, path)]


def _section_unit(document: ReviewDocument, section: SectionNode, path: Path) -> Jednostka:
    paragraph = next((item for item in section.paragraphs if item.locator), None)
    locator = paragraph.locator if paragraph is not None else section.locator
    end = len(paragraph.text) if paragraph is not None else 0
    comments = tuple(
        comment
        for item in section.paragraphs
        for comment in comments_for_locator(document.comments, item.locator)
    )
    return _unit(
        Poziom.ROZDZIAL,
        section.id,
        section.text,
        path,
        locator,
        0,
        end,
        comments,
    )


def _document_unit(document: ReviewDocument, path: Path) -> Jednostka:
    paragraph = next((item for item in document.iter_paragraphs() if item.locator), None)
    locator = paragraph.locator if paragraph is not None else None
    end = len(paragraph.text) if paragraph is not None else 0
    return _unit(
        Poziom.CALOSC,
        document.id,
        document.text,
        path,
        locator,
        0,
        end,
        tuple(document.comments),
    )


def _unit(
    poziom: Poziom,
    node_id: str,
    text: str,
    path: Path,
    locator: str | None,
    char_start: int,
    char_end: int,
    comments: tuple[DocxComment, ...],
    *,
    visit: int = 0,
    document_pass: int = 0,
) -> Jednostka:
    return Jednostka(
        poziom,
        node_id,
        text,
        path,
        locator,
        char_start,
        char_end,
        comments,
        visit,
        document_pass,
    )


def with_visit(unit: Jednostka, visit: int, document_pass: int) -> Jednostka:
    return Jednostka(
        unit.poziom,
        unit.node_id,
        unit.text,
        unit.path,
        unit.locator,
        unit.char_start,
        unit.char_end,
        unit.comments,
        visit,
        document_pass,
    )


def _sentence_span(paragraph: ParagraphNode, sentence: SentenceNode) -> tuple[int, int]:
    start = sentence.char_start if sentence.char_start is not None else 0
    end = sentence.char_end if sentence.char_end is not None else start + len(sentence.text)
    return start, end


def _overlapping(
    paragraph: ParagraphNode,
    document: ReviewDocument,
    start: int,
    end: int,
) -> tuple[DocxComment, ...]:
    comments = comments_for_locator(document.comments, paragraph.locator)
    matched: list[DocxComment] = []
    for comment in comments:
        if comment.start_offset is None or comment.end_offset is None:
            matched.append(comment)
            continue
        if comment.start_offset < end and start < comment.end_offset:
            matched.append(comment)
    return tuple(matched)


__all__ = ["Jednostka", "list_units", "with_visit"]

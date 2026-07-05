"""Internal document tree used by hierarchical review."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, Field


class SentenceNode(BaseModel):
    id: str
    text: str
    paragraph_id: str
    char_start: int | None = None
    char_end: int | None = None
    locator: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ParagraphNode(BaseModel):
    id: str
    text: str
    section_id: str
    locator: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    sentences: list[SentenceNode] = Field(default_factory=list)
    # Spans of ``text`` contributed by non-editable inline content (tabs, breaks,
    # hyperlink/field text, ...). Coordinates match ``text`` (post-strip). Filled by
    # the DOCX parser; empty for plain-text paragraphs or unknown layouts.
    opaque_ranges: list[tuple[int, int]] = Field(default_factory=list)


class SectionNode(BaseModel):
    id: str
    title: str | None = None
    locator: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    paragraphs: list[ParagraphNode] = Field(default_factory=list)

    @property
    def text(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        parts.extend(paragraph.text for paragraph in self.paragraphs)
        return "\n\n".join(part for part in parts if part.strip())


class ReviewDocument(BaseModel):
    id: str = "document"
    source_path: Path | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    sections: list[SectionNode] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(section.text for section in self.sections if section.text.strip())

    def iter_sections(self) -> Iterator[SectionNode]:
        yield from self.sections

    def iter_paragraphs(self) -> Iterator[ParagraphNode]:
        for section in self.sections:
            yield from section.paragraphs

    def iter_sentences(self) -> Iterator[SentenceNode]:
        for paragraph in self.iter_paragraphs():
            yield from paragraph.sentences

    def paragraph_for_sentence(self, sentence_id: str) -> ParagraphNode | None:
        for paragraph in self.iter_paragraphs():
            if any(sentence.id == sentence_id for sentence in paragraph.sentences):
                return paragraph
        return None

    def get_node_text(self, node_id: str) -> str | None:
        if node_id == self.id:
            return self.text

        for section in self.sections:
            if section.id == node_id:
                return section.text
            for paragraph in section.paragraphs:
                if paragraph.id == node_id:
                    return paragraph.text
                for sentence in paragraph.sentences:
                    if sentence.id == node_id:
                        return sentence.text
        return None

    def sentence_ids_for_paragraph(self, paragraph: ParagraphNode) -> set[str]:
        return {sentence.id for sentence in paragraph.sentences}

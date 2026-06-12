"""Traversal helpers for the internal document tree."""

from __future__ import annotations

from collections.abc import Iterator

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode


class DocumentWalker:
    def __init__(self, document: ReviewDocument) -> None:
        self.document = document

    def sections(self) -> Iterator[SectionNode]:
        yield from self.document.iter_sections()

    def paragraphs(self, section: SectionNode) -> Iterator[ParagraphNode]:
        yield from section.paragraphs

    def sentences(self, paragraph: ParagraphNode) -> Iterator[SentenceNode]:
        yield from paragraph.sentences

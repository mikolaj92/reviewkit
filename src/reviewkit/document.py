"""Internal document tree used by the one-DOCX walk."""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from reviewkit.comments import DocxComment


class SourceRevisionKind(StrEnum):
    INSERTED = "inserted"
    DELETED = "deleted"


class RevisionCoverageState(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class SourceRevision(BaseModel):
    """One addressable source revision span projected from Docxtor."""

    model_config = ConfigDict(frozen=True)

    kind: SourceRevisionKind
    text: str
    locator: str
    span_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    revision_id: str | None = None
    author: str | None = None
    date: str | None = None
    paragraph_mark: bool = False


class RevisionLedger(BaseModel):
    """Typed source-revision coverage and entries for one review document."""

    model_config = ConfigDict(frozen=True)

    coverage: RevisionCoverageState
    entries: tuple[SourceRevision, ...] = ()


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
    opaque_ranges: list[tuple[int, int]] = Field(default_factory=list)
    comments: list[DocxComment] = Field(default_factory=list)


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
    comments: list[DocxComment] = Field(default_factory=list)
    revision_ledger: RevisionLedger = Field(
        default_factory=lambda: RevisionLedger(coverage=RevisionCoverageState.COMPLETE)
    )

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

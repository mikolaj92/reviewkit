"""Bounded semantic-review units: schema, timeout, shape, and section size.

Host-owned. No document body text in diagnostics. Domain-blind: no legal
vocabulary, no consumer names.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode
from reviewkit.models import ReviewBoundError, ReviewFailureClass

DEFAULT_SECTION_CHAR_BUDGET = 4000
DEFAULT_MAX_RETRIES = 1


def validate_review_payload(
    payload: object,
    schema: type[BaseModel],
    *,
    node_id: str,
    budget: int | None = None,
    retry_count: int = 0,
) -> BaseModel:
    """Accept only the declared object schema. Lists and other roots fail closed."""
    if isinstance(payload, list):
        raise ReviewBoundError(
            failure_class=ReviewFailureClass.UNSUPPORTED_SHAPE,
            node_id=node_id,
            budget=budget,
            retry_count=retry_count,
            reason=f"expected {schema.__name__} object, got list",
        )
    if not isinstance(payload, (dict, BaseModel)):
        raise ReviewBoundError(
            failure_class=ReviewFailureClass.UNSUPPORTED_SHAPE,
            node_id=node_id,
            budget=budget,
            retry_count=retry_count,
            reason=f"expected {schema.__name__} object, got {type(payload).__name__}",
        )
    try:
        if isinstance(payload, BaseModel):
            return schema.model_validate(payload.model_dump(mode="json"))
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise ReviewBoundError(
            failure_class=ReviewFailureClass.SCHEMA_MISMATCH,
            node_id=node_id,
            budget=budget,
            retry_count=retry_count,
            reason=f"{schema.__name__} ({exc.error_count()} error(s))",
        ) from exc


def bound_document_sections(
    document: ReviewDocument,
    char_budget: int,
) -> ReviewDocument:
    """Split oversized sections at paragraph locators. Preserve order.

    A single paragraph over the budget fails closed: there is no smaller
    stable document boundary.
    """
    if char_budget <= 0:
        raise ReviewBoundError(
            failure_class=ReviewFailureClass.OVERSIZE_UNIT,
            node_id=document.id,
            budget=char_budget,
            reason="section_char_budget must be positive",
        )
    sections: list[SectionNode] = []
    for section in document.sections:
        sections.extend(_split_section(section, char_budget))
    return document.model_copy(update={"sections": sections})


def _split_section(section: SectionNode, char_budget: int) -> list[SectionNode]:
    if len(section.text) <= char_budget:
        return [section]
    if not section.paragraphs:
        raise ReviewBoundError(
            failure_class=ReviewFailureClass.OVERSIZE_UNIT,
            node_id=section.id,
            budget=char_budget,
            reason="section exceeds budget with no paragraph boundary",
        )
    chunks: list[list[ParagraphNode]] = []
    current: list[ParagraphNode] = []
    current_len = len(section.title or "")
    for paragraph in section.paragraphs:
        para_len = len(paragraph.text)
        if para_len > char_budget:
            raise ReviewBoundError(
                failure_class=ReviewFailureClass.OVERSIZE_UNIT,
                node_id=paragraph.id,
                budget=char_budget,
                reason="paragraph exceeds budget; no smaller locator",
            )
        extra = para_len + (2 if current else 0)
        if current and current_len + extra > char_budget:
            chunks.append(current)
            current = [paragraph]
            current_len = para_len
            continue
        current.append(paragraph)
        current_len += extra
    if current:
        chunks.append(current)
    out: list[SectionNode] = []
    for index, paragraphs in enumerate(chunks):
        first = paragraphs[0]
        out.append(
            SectionNode(
                id=f"{section.id}:chunk:{index}",
                title=section.title if index == 0 else None,
                locator=first.locator or section.locator,
                metadata=dict(section.metadata),
                paragraphs=list(paragraphs),
            )
        )
    return out


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_SECTION_CHAR_BUDGET",
    "bound_document_sections",
    "validate_review_payload",
]

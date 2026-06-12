"""Extensible context injection for hierarchical review prompts."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.models import ReviewScope
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState

ReviewNode = SentenceNode | ParagraphNode | SectionNode | ReviewDocument


class ReviewContext(BaseModel):
    scope: ReviewScope
    node_id: str
    data: dict[str, Any] = Field(default_factory=dict)


class ReviewContextProvider(Protocol):
    def context_for(
        self,
        *,
        profile: ReviewProfile,
        document: ReviewDocument,
        state: ReviewState,
        scope: ReviewScope,
        node: ReviewNode,
    ) -> ReviewContext: ...


class EmptyReviewContextProvider:
    def context_for(
        self,
        *,
        profile: ReviewProfile,
        document: ReviewDocument,
        state: ReviewState,
        scope: ReviewScope,
        node: ReviewNode,
    ) -> ReviewContext:
        return ReviewContext(scope=scope, node_id=node.id)

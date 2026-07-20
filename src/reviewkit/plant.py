"""ReviewKit document plant for takt 0.2.0 host integration.

Builds a domain tree (sentence → paragraph → section → document) and exposes
post-order scan plus JSON plant_nodes for the Mojo cascade step.

Takt has no document parser — the host owns plant construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from reviewkit.document import (
    ParagraphNode,
    ReviewDocument,
    SectionNode,
    SentenceNode,
)
from reviewkit.models import ReviewScope
from reviewkit.takt_types import PlantNode


class DocNode:
    """Wrapper around a review node with children for hierarchical scan."""

    def __init__(
        self,
        inner: SentenceNode | ParagraphNode | SectionNode | ReviewDocument,
        children: list[DocNode],
        *,
        parent_id: str = "",
        layer: int = 0,
        kind: str = "node",
    ) -> None:
        self.inner = inner
        self._children = children
        self.parent_id = parent_id
        self.layer = layer
        self.kind = kind

    @property
    def id(self) -> str:
        return getattr(self.inner, "id", str(id(self.inner)))

    @property
    def value(self) -> Any:
        return self.inner

    def get_children(self) -> Sequence[DocNode]:
        return self._children

    def has_children(self) -> bool:
        return bool(self._children)

    def scope(self) -> ReviewScope | None:
        if isinstance(self.inner, SentenceNode):
            return ReviewScope.SENTENCE
        if isinstance(self.inner, ParagraphNode):
            return ReviewScope.PARAGRAPH
        if isinstance(self.inner, SectionNode):
            return ReviewScope.SECTION
        if isinstance(self.inner, ReviewDocument):
            return ReviewScope.DOCUMENT
        return None

    def to_plant_node(self, *, value: float = 0.0) -> PlantNode:
        return PlantNode(
            id=self.id,
            value=value,
            has_children=self.has_children(),
            parent_id=self.parent_id,
            layer=self.layer,
            kind=self.kind,
        )

    def __repr__(self) -> str:
        kind = type(self.inner).__name__
        return f"DocNode({kind}, {self.id!r})"


# Backward-compatible alias used by tests / older imports
_DocNode = DocNode


@dataclass
class ReviewDocumentPlant:
    """Host plant over a ReviewDocument.

    sequential_scan yields nodes in post-order (deepest first) so lower-scope
    tacts finish before their containing higher-scope node.
    """

    document: ReviewDocument
    scope_layers: dict[ReviewScope, int] = field(default_factory=dict)
    root: DocNode = field(init=False)
    _index: dict[str, DocNode] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.scope_layers:
            # Default pipeline order as layer indices
            self.scope_layers = {
                ReviewScope.SENTENCE: 0,
                ReviewScope.PARAGRAPH: 1,
                ReviewScope.SECTION: 2,
                ReviewScope.DOCUMENT: 3,
            }
        self.root = self._build_tree(self.document)
        self._index = {}
        self._build_index(self.root)

    def _layer_for(self, scope: ReviewScope) -> int:
        return self.scope_layers.get(scope, 0)

    def _build_tree(self, doc: ReviewDocument) -> DocNode:
        def wrap_sentence(s: SentenceNode, parent_id: str) -> DocNode:
            return DocNode(
                s,
                [],
                parent_id=parent_id,
                layer=self._layer_for(ReviewScope.SENTENCE),
                kind="sentence",
            )

        def wrap_paragraph(p: ParagraphNode, parent_id: str) -> DocNode:
            sents = [wrap_sentence(s, p.id) for s in p.sentences]
            return DocNode(
                p,
                sents,
                parent_id=parent_id,
                layer=self._layer_for(ReviewScope.PARAGRAPH),
                kind="paragraph",
            )

        def wrap_section(sec: SectionNode, parent_id: str) -> DocNode:
            paras = [wrap_paragraph(p, sec.id) for p in sec.paragraphs]
            return DocNode(
                sec,
                paras,
                parent_id=parent_id,
                layer=self._layer_for(ReviewScope.SECTION),
                kind="section",
            )

        sections = [wrap_section(sec, doc.id) for sec in doc.sections]
        return DocNode(
            doc,
            sections,
            parent_id="",
            layer=self._layer_for(ReviewScope.DOCUMENT),
            kind="document",
        )

    def _build_index(self, node: DocNode) -> None:
        self._index[node.id] = node
        for ch in node.get_children():
            self._build_index(ch)

    def sequential_scan(self) -> Iterator[DocNode]:
        """Post-order: children before parent."""

        def post(n: DocNode) -> Iterator[DocNode]:
            for c in n.get_children():
                yield from post(c)
            yield n

        return post(self.root)

    def get_node(self, node_id: str) -> DocNode | None:
        return self._index.get(node_id)

    def to_plant_nodes(self) -> list[PlantNode]:
        """Full plant in DFS/post-order as takt plant_nodes JSON."""
        return [n.to_plant_node() for n in self.sequential_scan()]


__all__ = ["ReviewDocumentPlant", "DocNode", "_DocNode"]

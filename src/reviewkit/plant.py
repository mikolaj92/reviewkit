"""ReviewKit as ControlledPlant for takt 0.1.2.

Provides StateNode adapters and ControlledPlant over the existing
ReviewDocument / Section / Paragraph / Sentence tree.

Scan order: post-order (children before parents) so that when a parent
node is tacted, all its subtree children have already been processed.
This matches the old hierarchical roll-up (sentences -> paragraph -> ...).

value is the inner node object (default numeric detector is skipped safely).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

from takt import ControlledPlant, StateNode

from reviewkit.document import (
    ParagraphNode,
    ReviewDocument,
    SectionNode,
    SentenceNode,
)


class _DocNode(StateNode[Any]):
    """Wrapper making any review node satisfy takt StateNode protocol."""

    def __init__(
        self,
        inner: SentenceNode | ParagraphNode | SectionNode | ReviewDocument,
        children: list[_DocNode],
    ) -> None:
        self.inner = inner
        self._children = children

    @property
    def id(self) -> str:
        return getattr(self.inner, "id", str(id(self.inner)))

    @property
    def value(self) -> Any:
        # Return the inner object. The fallback numeric detector in takt
        # will catch the TypeError and skip. Real detectors ignore .value.
        return self.inner

    def get_children(self) -> Sequence[StateNode[Any]]:
        return self._children

    def has_children(self) -> bool:
        # Always return True so that the takt CascadeRegulator child_loop descent
        # reaches the matching layer's detector for every node we tact.
        # Layer selection (sentence layer only acts on sentence nodes etc.) is done
        # by the strict guards inside the detectors. The document tree structure
        # still controls get_children() for the actual StateNode children.
        return True
    def __repr__(self) -> str:
        kind = type(self.inner).__name__
        return f"_DocNode({kind}, {self.id!r})"


@dataclass
class ReviewDocumentPlant(ControlledPlant[Any]):
    """ControlledPlant for a ReviewDocument.

    sequential_scan yields nodes in post-order (deepest first).
    This ensures lower-scope tacts happen before their containing higher-scope node.
    """

    document: ReviewDocument
    root: _DocNode = field(init=False)
    _index: dict[str, _DocNode] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = self._build_tree(self.document)
        self._index = {}
        self._build_index(self.root)

    def _build_tree(self, doc: ReviewDocument) -> _DocNode:
        def wrap_sentence(s: SentenceNode) -> _DocNode:
            return _DocNode(s, [])

        def wrap_paragraph(p: ParagraphNode) -> _DocNode:
            sents = [wrap_sentence(s) for s in p.sentences]
            return _DocNode(p, sents)

        def wrap_section(sec: SectionNode) -> _DocNode:
            paras = [wrap_paragraph(p) for p in sec.paragraphs]
            return _DocNode(sec, paras)

        sections = [wrap_section(sec) for sec in doc.sections]
        return _DocNode(doc, sections)

    def _build_index(self, node: _DocNode) -> None:
        self._index[node.id] = node
        for ch in node.get_children():
            self._build_index(ch)

    def sequential_scan(self) -> Iterator[StateNode[Any]]:
        """Post-order: children before parent. Matches old bottom-up review."""
        def post(n: _DocNode) -> Iterator[StateNode[Any]]:
            for c in n.get_children():
                yield from post(c)
            yield n

        return post(self.root)

    def get_node(self, node_id: str) -> _DocNode | None:
        return self._index.get(node_id)


__all__ = ["ReviewDocumentPlant", "_DocNode"]

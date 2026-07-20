"""Host-side LLM detectors for takt 0.2.0.

Detectors produce ``RawSignal`` lists that ReviewKit ships to the Mojo
cascade step (or local fusion). Takt itself does not run LLMs.
"""

from __future__ import annotations

from typing import Any

from reviewkit.context import ReviewContextProvider
from reviewkit.document import (
    ParagraphNode,
    ReviewDocument,
    SectionNode,
    SentenceNode,
)
from reviewkit.llm import LLMClient
from reviewkit.models import (
    ReviewAction,
    ReviewScope,
    SentenceReviewResponse,
    ParagraphReviewResponse,
    SectionReviewResponse,
    DocumentReviewResponse,
)
from reviewkit.profile import ReviewProfile
from reviewkit.prompts import (
    document_review_prompt,
    paragraph_review_prompt,
    section_review_prompt,
    sentence_review_prompt,
)
from reviewkit.state import ReviewState
from reviewkit.takt_types import RawSignal


def _rollup_actions_for_prompt(
    scope: ReviewScope,
    inner: Any,
    actions: list[ReviewAction],
    pipeline: list[ReviewScope],
) -> list[ReviewAction]:
    """Collect lower-level actions visible to the next scope (legacy roll-up)."""
    enabled = set(pipeline)
    if scope == ReviewScope.PARAGRAPH:
        if not isinstance(inner, ParagraphNode):
            return []
        sent_ids = {s.id for s in inner.sentences}
        return [
            a
            for a in actions
            if a.scope == ReviewScope.SENTENCE and a.node_id in sent_ids
        ]
    if scope == ReviewScope.SECTION:
        if not isinstance(inner, SectionNode):
            return []
        para_ids = {p.id for p in inner.paragraphs}
        sent_ids: set[str] = set()
        for p in inner.paragraphs:
            sent_ids.update(s.id for s in p.sentences)
        rolled: list[ReviewAction] = []
        for a in actions:
            if a.scope == ReviewScope.PARAGRAPH and a.node_id in para_ids:
                rolled.append(a)
            elif (
                ReviewScope.PARAGRAPH not in enabled
                and a.scope == ReviewScope.SENTENCE
                and a.node_id in sent_ids
            ):
                rolled.append(a)
        return rolled
    if scope == ReviewScope.DOCUMENT:
        if not isinstance(inner, ReviewDocument):
            return []
        section_ids = {s.id for s in inner.sections}
        para_ids: set[str] = set()
        for sec in inner.sections:
            para_ids.update(p.id for p in sec.paragraphs)
        rolled_doc: list[ReviewAction] = []
        for a in actions:
            if a.scope == ReviewScope.SECTION and a.node_id in section_ids:
                rolled_doc.append(a)
            elif (
                ReviewScope.SECTION not in enabled
                and a.scope == ReviewScope.PARAGRAPH
                and a.node_id in para_ids
            ):
                rolled_doc.append(a)
            elif (
                ReviewScope.SECTION not in enabled
                and ReviewScope.PARAGRAPH not in enabled
                and a.scope == ReviewScope.SENTENCE
            ):
                rolled_doc.append(a)
        return rolled_doc
    return []


class BaseLLMDetector:
    """Base for scope-specific LLM detectors."""

    def __init__(
        self,
        profile: ReviewProfile,
        llm: LLMClient,
        context_provider: ReviewContextProvider,
        state: ReviewState,
        scope: ReviewScope,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.context_provider = context_provider
        self.state = state
        self.scope = scope
        self._document: ReviewDocument | None = None

    def set_document(self, document: ReviewDocument) -> None:
        self._document = document

    def _complete(self, messages: list[dict[str, str]], schema: type) -> Any:
        return self.llm.complete_json(messages, schema)

    def detect(self, node: Any) -> list[RawSignal]:
        inner = getattr(node, "inner", node)
        node_id = getattr(inner, "id", str(id(inner)))

        # Strict guard: this layer only produces signals for its own node type.
        if self.scope == ReviewScope.SENTENCE and not isinstance(inner, SentenceNode):
            return []
        if self.scope == ReviewScope.PARAGRAPH and not isinstance(inner, ParagraphNode):
            return []
        if self.scope == ReviewScope.SECTION and not isinstance(inner, SectionNode):
            return []
        if self.scope == ReviewScope.DOCUMENT and not isinstance(inner, ReviewDocument):
            return []

        doc_for_context = self._document
        context = self.context_provider.context_for(
            profile=self.profile,
            document=doc_for_context,
            state=self.state,
            scope=self.scope,
            node=inner,
        )

        if self.scope == ReviewScope.SENTENCE:
            prompt = sentence_review_prompt(self.profile, self.state, inner, context)
            resp = self._complete(prompt, SentenceReviewResponse)
            return _response_to_signals(resp, node_id, "llm_sentence", self.scope)

        lower = getattr(self, "_lower_actions_for_prompt", None) or []

        if self.scope == ReviewScope.PARAGRAPH:
            prompt = paragraph_review_prompt(
                self.profile, self.state, inner, lower, context
            )
            resp = self._complete(prompt, ParagraphReviewResponse)
            return _response_to_signals(resp, node_id, "llm_paragraph", self.scope)

        if self.scope == ReviewScope.SECTION:
            prompt = section_review_prompt(
                self.profile, self.state, inner, lower, context
            )
            resp = self._complete(prompt, SectionReviewResponse)
            return _response_to_signals(resp, node_id, "llm_section", self.scope)

        if self.scope == ReviewScope.DOCUMENT:
            prompt = document_review_prompt(
                self.profile, self.state, inner, lower, context
            )
            resp = self._complete(prompt, DocumentReviewResponse)
            return _response_to_signals(resp, node_id, "llm_document", self.scope)

        return []


def _response_to_signals(
    response: Any,
    node_id: str,
    detector_name: str,
    scope: ReviewScope,
) -> list[RawSignal]:
    """Convert a review response into one or more RawSignals."""
    signals: list[RawSignal] = []

    for finding in getattr(response, "findings", []):
        sev = getattr(finding, "severity", "medium")
        conf = float(getattr(finding, "confidence", 0.5))
        dev = _severity_to_deviation(sev) * (1.0 if conf > 0.3 else 0.3)
        signals.append(
            RawSignal(
                signal_id=f"finding:{finding.finding_id or finding.title}",
                node_id=node_id,
                detector=f"{detector_name}.finding",
                deviation=dev,
                confidence=conf,
                evidence={
                    "title": finding.title,
                    "description": finding.description,
                    "dimension": str(finding.dimension) if finding.dimension else None,
                    "scope": scope.value,
                },
            )
        )

    for action in getattr(response, "actions", []):
        conf = float(getattr(action, "confidence", 0.5))
        sev = getattr(action, "severity", "medium")
        dev = _severity_to_deviation(sev) * 1.2
        signals.append(
            RawSignal(
                signal_id=f"action:{getattr(action, 'id', action.action_type)}",
                node_id=node_id,
                detector=f"{detector_name}.action",
                deviation=dev,
                confidence=conf,
                evidence={
                    "action_type": str(action.action_type),
                    "reason": getattr(action, "reason", None),
                    "scope": scope.value,
                    "requires_human": getattr(action, "requires_human_decision", False),
                },
            )
        )

    return signals


def _severity_to_deviation(severity: str) -> float:
    mapping = {
        "info": 0.15,
        "low": 0.4,
        "medium": 0.65,
        "high": 0.9,
        "critical": 1.0,
    }
    return mapping.get(str(severity).lower(), 0.6)


__all__ = ["BaseLLMDetector", "_response_to_signals", "_rollup_actions_for_prompt"]

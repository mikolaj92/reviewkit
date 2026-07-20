"""Takt 0.2.0-based hierarchical review orchestration for ReviewKit.

Host (ReviewKit) owns:
  - document plant construction
  - LLM detectors → RawSignal
  - mapping decisions back to ReviewAction / findings

Takt (Mojo cascade, or local 0.2.0-compatible fallback) owns:
  - fusion of raw signals
  - homeostat → actuation / interlock / stable

Flow per matching node (post-order):
1. Plant yields node (sentence, paragraph, section, document).
2. Scope detector runs LLM → RawSignals + stored response.
3. TaktClient.evaluate(plant_node, layers, raw_signals) → TaktDecision.
4. ReviewEffector materializes ReviewActions with status.
5. Deterministic post-processing preserves the public output contract.
"""

from __future__ import annotations

from typing import Any

from reviewkit.context import EmptyReviewContextProvider, ReviewContextProvider
from reviewkit.detectors import BaseLLMDetector, _rollup_actions_for_prompt
from reviewkit.document import ReviewDocument
from reviewkit.effectors import ReviewEffector
from reviewkit.homeostat import build_layer_specs, scope_to_layer_index
from reviewkit.llm import LLMClient
from reviewkit.models import ReviewAction, ReviewFinding, ReviewScope
from reviewkit.plant import DocNode, ReviewDocumentPlant
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState
from reviewkit.takt_client import TaktClient
from reviewkit.takt_types import LayerSpec, RawSignal


class TaktReviewer:
    """Full takt 0.2.0 driven reviewer (Mojo cascade via host boundary)."""

    def __init__(
        self,
        profile: ReviewProfile,
        llm: LLMClient,
        context_provider: ReviewContextProvider | None = None,
        action_policy: ActionPolicy | None = None,
        *,
        propagate_llm_errors: bool = False,
        takt_client: TaktClient | None = None,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.context_provider = context_provider or EmptyReviewContextProvider()
        self.action_policy = action_policy
        self.propagate_llm_errors = propagate_llm_errors
        self.takt_client = takt_client or TaktClient()

    def review(
        self, document: ReviewDocument
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        state = ReviewState()
        effector = ReviewEffector(state)

        layers = build_layer_specs(self.profile)
        layer_by_scope = scope_to_layer_index(self.profile)
        plant = ReviewDocumentPlant(document, scope_layers=layer_by_scope)

        detectors = self._build_detectors(document, state, effector)
        enabled = set(self.profile.review_pipeline)

        accumulated_lower_actions: list[ReviewAction] = []
        for node in plant.sequential_scan():
            scope = node.scope()
            if scope is None or scope not in enabled:
                continue

            detector = detectors[scope]
            detector.set_lower_actions(accumulated_lower_actions)

            signals = detector.detect(node)
            # Even with empty signals we still evaluate (stable / intrinsic value).
            decision = self.takt_client.evaluate(
                plant_nodes=[node.to_plant_node(value=0.0)],
                layers=layers or [LayerSpec(layer=0)],
                raw_signals=signals,
            )
            effector.apply_takt_decision(node.id, decision)
            accumulated_lower_actions = effector.actions

        from reviewkit.actions import prepare_actions, demote_cross_scope_overlaps

        prepared = prepare_actions(
            document, self.profile, effector.actions, policy=self.action_policy
        )
        final_actions = demote_cross_scope_overlaps(document, prepared)

        deduped_findings: list[ReviewFinding] = []
        seen: dict[str, bool] = {}
        for f in effector.findings:
            key = f.finding_id or (f.title + "|" + f.node_id)
            if key not in seen:
                seen[key] = True
                deduped_findings.append(f)

        return deduped_findings, final_actions, state

    def _build_detectors(
        self,
        document: ReviewDocument,
        state: ReviewState,
        effector: ReviewEffector,
    ) -> dict[ReviewScope, _LLMDetectorAdapter]:
        pipeline = self.profile.review_pipeline
        detectors: dict[ReviewScope, _LLMDetectorAdapter] = {}
        for scope in pipeline:
            det = _LLMDetectorAdapter(
                profile=self.profile,
                llm=self.llm,
                context_provider=self.context_provider,
                state=state,
                scope=scope,
                document=document,
                effector=effector,
                pipeline=pipeline,
                propagate_llm_errors=self.propagate_llm_errors,
            )
            det.inner.set_document(document)
            detectors[scope] = det
        return detectors


class _LLMDetectorAdapter:
    """Runs BaseLLMDetector and stores the LLM response for the effector."""

    def __init__(
        self,
        *,
        profile: ReviewProfile,
        llm: LLMClient,
        context_provider: ReviewContextProvider,
        state: ReviewState,
        scope: ReviewScope,
        document: ReviewDocument,
        effector: ReviewEffector,
        pipeline: list[ReviewScope],
        propagate_llm_errors: bool,
    ) -> None:
        self.inner = BaseLLMDetector(
            profile=profile,
            llm=llm,
            context_provider=context_provider,
            state=state,
            scope=scope,
        )
        self.scope = scope
        self.document = document
        self.effector = effector
        self.pipeline = pipeline
        self.propagate_llm_errors = propagate_llm_errors
        self._lower_actions: list[ReviewAction] = []

    def set_lower_actions(self, actions: list[ReviewAction]) -> None:
        self._lower_actions = list(actions or [])

    def detect(self, node: DocNode | Any) -> list[RawSignal]:
        inner_node = getattr(node, "inner", node)
        effective_scope = self.scope
        if isinstance(inner_node, ReviewDocument):
            effective_scope = ReviewScope.DOCUMENT

        rolled = _rollup_actions_for_prompt(
            self.scope, inner_node, self._lower_actions, self.pipeline
        )
        self.inner._lower_actions_for_prompt = rolled  # type: ignore[attr-defined]

        original_complete = self.inner._complete
        captured: dict[str, Any] = {"resp": None}

        def capturing_complete(messages: list[dict[str, str]], schema: type) -> Any:
            resp = original_complete(messages, schema)
            captured["resp"] = resp
            return resp

        self.inner._complete = capturing_complete  # type: ignore[method-assign]

        try:
            signals = self.inner.detect(node)
        except Exception as error:
            if self.propagate_llm_errors:
                raise
            label = f"{self.scope.value} {getattr(inner_node, 'id', '?')}"
            self.inner.state.warnings.append(
                f"LLM review skipped for {label}: {type(error).__name__}: {error}"
            )
            signals = []
        finally:
            self.inner._complete = original_complete  # type: ignore[method-assign]
            if hasattr(self.inner, "_lower_actions_for_prompt"):
                delattr(self.inner, "_lower_actions_for_prompt")

        resp = captured["resp"]
        if resp is not None:
            node_id = getattr(node, "id", getattr(inner_node, "id", "?"))
            self.effector.register_response(node_id, effective_scope, resp)

        return signals


__all__ = ["TaktReviewer"]

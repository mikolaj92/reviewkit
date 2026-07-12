"""Takt-based hierarchical review orchestration for ReviewKit.

This is the total replacement for the old HierarchicalReviewer.

Flow per node (post-order from ReviewDocumentPlant):
1. Plant yields node (sentence, paragraph, section, document).
2. Per-layer CascadeRegulator (with registered LLMDetector) collects RawSignals.
3. Splot + ProfilHomeostatyczny decide Actuation / SafetyInterlock.
4. ReviewEffector turns the decision + LLM response into ReviewAction(s) with status.
5. ReviewState is populated for prompt context (findings roll up via old state for now).

After the full cascade run we still run deterministic post-processing
(demote_cross_scope_overlaps, etc.) to keep output contract identical.
"""

from __future__ import annotations

from typing import Any
from takt import build_cascade
from reviewkit.context import EmptyReviewContextProvider, ReviewContextProvider
from reviewkit.detectors import BaseLLMDetector
from reviewkit.document import ReviewDocument
from reviewkit.effectors import ReviewEffector
from reviewkit.homeostat import build_layered_homeostats
from reviewkit.llm import LLMClient
from reviewkit.models import ReviewAction, ReviewFinding, ReviewScope
from reviewkit.plant import ReviewDocumentPlant
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState


class TaktReviewer:
    """Full takt 0.1.1 driven reviewer.

    Replaces the manual for-loop hierarchy.
    """

    def __init__(
        self,
        profile: ReviewProfile,
        llm: LLMClient,
        context_provider: ReviewContextProvider | None = None,
        action_policy: ActionPolicy | None = None,
        *,
        propagate_llm_errors: bool = False,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.context_provider = context_provider or EmptyReviewContextProvider()
        self.action_policy = action_policy
        self.propagate_llm_errors = propagate_llm_errors

    def review(
        self, document: ReviewDocument
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        state = ReviewState()
        effector = ReviewEffector(state)

        # 1. Plant over the document tree (post-order scan)
        plant = ReviewDocumentPlant(document)

        # 2. Homeostats per enabled scope/layer
        layered = build_layered_homeostats(self.profile)

        # 3. Build the cascade
        root_reg = build_cascade(layered)

        # 4. Attach detectors to each regulator in the cascade
        self._attach_detectors(root_reg, document, state, effector)

        # 5. Manual full-cascade walk (Lmax → L0) for every node in post-order.
        # This ensures every scope's detector fires exactly once for its matching nodes.
        from takt import OutgoingSignals

        nodes = list(plant.sequential_scan())

        regulators: list[Any] = []
        r = root_reg
        while r is not None:
            regulators.append(r)
            r = r.child_loop

        accumulated_lower_actions: list[ReviewAction] = []
        for node in nodes:
            # Make lower results visible to this node's matching layer detector
            for det in self._layer_detectors.values():
                det.set_lower_actions(accumulated_lower_actions)

            # Walk the cascade high→low for this node; each layer's evaluate
            # will invoke its detector (guards ensure only matching scope calls LLM).
            incoming: Any = None
            final_out: OutgoingSignals | None = None
            for reg in regulators:
                out = reg.evaluate(node, incoming)
                if final_out is None:
                    final_out = out
                else:
                    merged_il = out.interlock or final_out.interlock
                    merged_act = None if merged_il else (out.actuation or final_out.actuation)
                    final_out = OutgoingSignals(
                        error=out.error,
                        actuation=merged_act,
                        interlock=merged_il,
                        telemetry=list(final_out.telemetry) + list(out.telemetry),
                        ascending_wave=out.ascending_wave or final_out.ascending_wave,
                    )
                incoming = out.ascending_wave

            if final_out is None:
                # Fallback (should not happen)
                final_out = OutgoingSignals(
                    error=None,
                    actuation=None,
                    interlock=None,
                    telemetry=[],
                    ascending_wave=None,
                )

            effector.apply_takt_decision(node.id, final_out)

            # After this node finished, its actions (if any) are visible to ancestors
            accumulated_lower_actions = effector.actions
        # 6. Post-processing retained for output contract parity (same as legacy)
        from reviewkit.actions import prepare_actions, demote_cross_scope_overlaps

        prepared = prepare_actions(
            document, self.profile, effector.actions, policy=self.action_policy
        )
        final_actions = demote_cross_scope_overlaps(document, prepared)
        # Dedup findings (same semantics as old ReviewState)
        deduped_findings: list[ReviewFinding] = []
        seen: dict[str, bool] = {}
        for f in effector.findings:
            key = f.finding_id or (f.title + "|" + f.node_id)
            if key not in seen:
                seen[key] = True
                deduped_findings.append(f)

        return deduped_findings, final_actions, state

    def _attach_detectors(
        self,
        root_reg: Any,  # CascadeRegulator
        document: ReviewDocument,
        state: ReviewState,
        effector: ReviewEffector,
    ) -> None:
        """Walk the regulator cascade and register the right detector per layer."""
        pipeline = self.profile.review_pipeline
        layer_to_scope = {i: scope for i, scope in enumerate(pipeline)}
        max_layer = len(pipeline) - 1 if pipeline else 0
        self._layer_detectors: dict[int, _LLMDetectorAdapter] = {}

        def attach(reg: Any, layer: int) -> None:
            scope = layer_to_scope.get(layer, ReviewScope.PARAGRAPH)
            detector = _LLMDetectorAdapter(
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
            reg.register_detector(detector)
            self._layer_detectors[layer] = detector
            if reg.child_loop is not None:
                attach(reg.child_loop, layer - 1)

        attach(root_reg, max_layer)
class _LLMDetectorAdapter:
    """Adapter so that takt's register_detector(detector) works.

    takt expects objects with .detect(node) -> list[RawSignal].
    We also capture the full LLM response for the effector.
    """

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
        self._last_response: Any = None
        self._lower_actions: list[ReviewAction] = []

    def set_lower_actions(self, actions: list[ReviewAction]) -> None:
        self._lower_actions = list(actions or [])

    def detect(self, node: Any) -> list:
        inner_node = getattr(node, "inner", node)
        effective_scope = self.scope
        if isinstance(inner_node, ReviewDocument):
            effective_scope = ReviewScope.DOCUMENT

        # Compute rolled lower results for this prompt (legacy semantics)
        from reviewkit.detectors import _rollup_actions_for_prompt
        rolled = _rollup_actions_for_prompt(
            self.scope, inner_node, self._lower_actions, self.pipeline
        )

        # Inject rolled lower results directly for this call (read by BaseLLMDetector.detect)
        self.inner._lower_actions_for_prompt = rolled  # type: ignore[attr-defined]

        original_complete = self.inner._complete
        captured = {"resp": None}

        def capturing_complete(messages, schema):
            resp = original_complete(messages, schema)
            captured["resp"] = resp
            return resp

        self.inner._complete = capturing_complete  # type: ignore

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
            self.inner._complete = original_complete  # type: ignore
            if hasattr(self.inner, "_lower_actions_for_prompt"):
                delattr(self.inner, "_lower_actions_for_prompt")
        resp = captured["resp"]
        if resp is not None:
            self.effector.register_response(node.id, effective_scope, resp)

        return signals

    def _response_to_raw_signals(self, resp: Any, node_id: str, scope: ReviewScope):
        from reviewkit.detectors import _response_to_signals
        return _response_to_signals(resp, node_id, f"llm_{scope.value}", scope)


__all__ = ["TaktReviewer"]

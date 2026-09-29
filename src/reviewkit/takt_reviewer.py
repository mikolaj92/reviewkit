"""Takt v0.3.2-based hierarchical review orchestration for ReviewKit.

Host (ReviewKit) owns:
  - document plant construction
  - LLM detectors → RawSignal
  - mapping decisions back to ReviewAction / findings

Takt's Mojo cascade owns:
  - fusion of raw signals
  - homeostat → actuation / interlock / stable

The official in-process binding is the only evaluation path; binding failures are
propagated and are never downgraded to a local compatibility engine.

Flow per matching node (post-order):
1. Plant yields node (sentence, paragraph, section, document).
2. Scope detector runs LLM → RawSignals + stored response.
3. TaktClient.evaluate(plant_node, layers, raw_signals) → TaktDecision.
4. ReviewEffector materializes ReviewActions with status.
5. Deterministic post-processing preserves the public output contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, cast

from reviewkit.context import EmptyReviewContextProvider, ReviewContextProvider
from reviewkit.decision import (
    DecisionAnswer,
    DecisionClient,
    Question,
    coerce_answer,
    document_present_question,
    fragment_verdict_question,
    is_noul_yes,
    naming_questions,
)
from reviewkit.detectors import BaseLLMDetector, _lower_actions_for_prompt
from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode, SentenceNode
from reviewkit.effectors import ReviewEffector
from reviewkit.homeostat import build_layer_specs, scope_to_layer_index
from reviewkit.llm import LLMClient
from reviewkit.models import (
    DocumentReviewResponse,
    FindingLineageEvent,
    ParagraphReviewResponse,
    ReconciliationDisposition,
    ReviewAction,
    ReviewActionType,
    ReviewFinding,
    ReviewLocator,
    ReviewScope,
    SectionReviewResponse,
    SentenceReviewResponse,
)
from reviewkit.pack import (
    ActionText,
    FunctionTag,
    NamingResponse,
    Pack,
    PassTrace,
    ProcessCheck,
    Rule,
    SourceUnit,
    Verdict,
    VerdictKind,
    accepted_tags,
    check_naming,
    cited_unit,
    function_label,
    judge_rules,
    naming_functions,
)
from reviewkit.plant import DocNode, ReviewDocumentPlant
from reviewkit.policy import ActionPolicy
from reviewkit.profile import ReviewProfile
from reviewkit.prompts import (
    action_prompt,
    reconciliation_review_prompt,
)
from reviewkit.reconciliation import reconcile_findings, select_reconciliation_targets
from reviewkit.review_bounds import (
    bound_document_sections,
    build_document_source_context,
)
from reviewkit.state import ReviewState
from reviewkit.takt_client import TaktClient
from reviewkit.takt_types import RawSignal

_ACTION_TYPE = {
    VerdictKind.CHANGE: ReviewActionType.REPLACE_TEXT,
    VerdictKind.DELETE: ReviewActionType.DELETE_TEXT,
    VerdictKind.INSERT: ReviewActionType.INSERT_TEXT,
    VerdictKind.MISSING: ReviewActionType.INSERT_TEXT,
}

_RESPONSE_SCHEMA = {
    ReviewScope.SENTENCE: SentenceReviewResponse,
    ReviewScope.PARAGRAPH: ParagraphReviewResponse,
    ReviewScope.SECTION: SectionReviewResponse,
    ReviewScope.DOCUMENT: DocumentReviewResponse,
}


def _verdict_kind(answer: DecisionAnswer) -> VerdictKind | None:
    if isinstance(answer.value, bool):
        return None
    try:
        return VerdictKind(str(answer.value).strip().lower())
    except ValueError:
        return None


class TaktReviewer:
    """Full takt v0.3.2-driven reviewer using the in-process Mojo binding."""

    def __init__(
        self,
        profile: ReviewProfile,
        llm: LLMClient,
        context_provider: ReviewContextProvider | None = None,
        action_policy: ActionPolicy | None = None,
        pack: Pack | None = None,
        decision: DecisionClient | None = None,
        *,
        takt_client: TaktClient | None = None,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.context_provider = context_provider or EmptyReviewContextProvider()
        self.action_policy = action_policy
        self.pack = pack
        self.decision = decision
        if self.pack is not None and self.decision is None:
            raise ValueError(
                "pack reviews name and judge through an injected DecisionClient; "
                "omit pack to keep the single LLMClient pass"
            )
        self.takt_client = takt_client or TaktClient()
        self.traces: list[PassTrace] = []

    def review(
        self, document: ReviewDocument
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        source_document = document
        document = bound_document_sections(document, self.profile.section_char_budget)
        document_source_context = None
        if ReviewScope.DOCUMENT in self.profile.review_pipeline:
            document_source_context = build_document_source_context(
                source_document,
                self.profile.document_source_char_budget,
            )
        state = ReviewState()
        self.state = state
        effector = ReviewEffector(state)

        layers = build_layer_specs(self.profile)
        layer_by_scope = scope_to_layer_index(self.profile)
        plant = ReviewDocumentPlant(document, scope_layers=layer_by_scope)

        detectors = self._build_detectors(
            document,
            state,
            effector,
            document_source_context=document_source_context,
        )
        enabled = set(self.profile.review_pipeline)

        if self.pack is not None:
            self._name(plant)

        accumulated_lower_actions: list[ReviewAction] = []
        scanned_nodes: dict[str, DocNode] = {}
        document_response: DocumentReviewResponse | None = None
        for node in plant.sequential_scan():
            scope = node.scope()
            if scope is None or scope not in enabled:
                continue

            scanned_nodes[node.id] = node
            detector = detectors[scope]
            if self.pack is not None:
                signals = detector.judge(node)
            else:
                detector.set_lower_actions(accumulated_lower_actions)
                signals = detector.detect(node)
            # Even with empty signals we still evaluate (stable / intrinsic value).
            decision = self.takt_client.evaluate(
                plant_nodes=[node.to_plant_node(value=0.0)],
                layers=layers,
                raw_signals=signals,
            )
            effector.apply_takt_decision(node.id, decision)
            accumulated_lower_actions = effector.actions
            if scope == ReviewScope.DOCUMENT and isinstance(
                detector.last_response, DocumentReviewResponse
            ):
                document_response = detector.last_response

        rereviewed: list[tuple[Any, ReviewFinding]] = []
        if self.profile.reconciliation_max_rounds and document_response is not None:
            targets = select_reconciliation_targets(
                document_response.reconciliation_requests,
                scanned_nodes,
                max_nodes=self.profile.reconciliation_max_nodes,
            )
            for request, node in targets:
                scope = node.scope()
                if scope is None or scope not in detectors:
                    continue
                response = detectors[scope].reconcile(node, request, state.document_summary)
                signals = detectors[scope].signals_for_response(response, node.id)
                decision = self.takt_client.evaluate(
                    plant_nodes=[node.to_plant_node(value=0.0)],
                    layers=layers,
                    raw_signals=signals,
                )
                effector.apply_takt_decision(node.id, decision)
                for finding in response.findings:
                    rereviewed.append((request, finding))

        from reviewkit.actions import demote_cross_scope_overlaps, prepare_actions

        prepared = prepare_actions(
            document, self.profile, effector.actions, policy=self.action_policy
        )
        final_actions = demote_cross_scope_overlaps(document, prepared)

        deduped_findings: list[ReviewFinding] = []
        seen: dict[str, bool] = {}
        rereview_ids = {id(finding) for _, finding in rereviewed}
        for f in effector.findings:
            if id(f) in rereview_ids:
                continue
            key = f.finding_id or (f.title + "|" + f.node_id)
            if key not in seen:
                seen[key] = True
                deduped_findings.append(f)
        deduped_findings = reconcile_findings(deduped_findings, rereviewed)

        return deduped_findings, final_actions, state

    def _name(self, plant: ReviewDocumentPlant) -> None:
        """First scan. Tags only: no cascade evaluation and no effector."""
        assert self.pack is not None
        assert self.decision is not None
        enabled = set(self.profile.review_pipeline)
        for node in plant.sequential_scan():
            scope = node.scope()
            if scope is None or scope not in enabled:
                continue
            inner = getattr(node, "inner", node)
            text = str(getattr(inner, "text", "") or "")
            functions = naming_functions(self.pack, scope)
            if not functions:
                continue
            questions = naming_questions(functions)
            answers = self.decision.decide(text, questions)
            tagged = [
                function_id
                for function_id, raw in answers.items()
                if function_id in questions and is_noul_yes(coerce_answer(raw))
            ]
            response = NamingResponse(
                tags=[FunctionTag(node_id=node.id, function_ids=tagged)] if tagged else []
            )
            self.traces.append(check_naming(self.pack, response))
            tag = next(
                (item for item in accepted_tags(self.pack, response) if item.node_id == node.id),
                None,
            )
            if tag is not None and tag.function_ids:
                self.state.tags.append(tag)

    def _build_detectors(
        self,
        document: ReviewDocument,
        state: ReviewState,
        effector: ReviewEffector,
        *,
        document_source_context: dict[str, Any] | None = None,
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
                document_source_context=(
                    document_source_context if scope == ReviewScope.DOCUMENT else None
                ),
                pack=self.pack,
                decision=self.decision,
                traces=self.traces,
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
        document_source_context: dict[str, Any] | None,
        pack: Pack | None = None,
        decision: DecisionClient | None = None,
        traces: list[PassTrace] | None = None,
    ) -> None:
        self.pack = pack
        self.decision = decision
        self.traces = traces if traces is not None else []
        self.inner = BaseLLMDetector(
            profile=profile,
            llm=llm,
            context_provider=context_provider,
            state=state,
            scope=scope,
            document_source_context=document_source_context,
        )
        self.scope = scope
        self.document = document
        self.effector = effector
        self._lower_actions: list[ReviewAction] = []
        self.last_response: Any = None

    def set_lower_actions(self, actions: list[ReviewAction]) -> None:
        self._lower_actions = list(actions or [])

    def judge(self, node: DocNode | Any) -> list[RawSignal]:
        """Second scan. Matched rules and the single unit each one cites.

        Pack reviews do not go through the fused ``detect()`` LLM path.
        """
        inner_node = getattr(node, "inner", node)
        effective_scope = self.scope
        if isinstance(inner_node, ReviewDocument):
            effective_scope = ReviewScope.DOCUMENT
        return self._judge_with_pack(node, effective_scope)

    def _judge_with_pack(self, node: DocNode | Any, scope: ReviewScope) -> list[RawSignal]:
        assert self.pack is not None
        node_id = getattr(node, "id", "?")
        function_ids = self.inner.state.functions_for(node_id)
        covered = self.inner.state.covered()
        rules = judge_rules(self.pack, scope, function_ids, covered)
        self.traces.append(
            PassTrace(
                checks=(
                    ProcessCheck(
                        name="fragment_has_no_close_rule",
                        passed=scope is ReviewScope.DOCUMENT
                        or not any(
                            rule.kind == "close" or rule.scope == "document" for rule in rules
                        ),
                    ),
                    ProcessCheck(
                        name="absence_is_document_scope",
                        passed=scope is ReviewScope.DOCUMENT
                        or not any(rule.when == "function_absent" for rule in rules),
                    ),
                )
            )
        )
        if not rules:
            return []
        units = {
            rule.function_id: unit
            for rule in rules
            if (unit := cited_unit(self.pack, getattr(rule, "source_unit_id", None))) is not None
        }
        verdicts = self._verdicts(node_id, scope, rules, units, function_ids)
        if not verdicts:
            return []
        response = _RESPONSE_SCHEMA[scope](
            findings=self._findings(verdicts),
            actions=self._actions(node_id, scope, verdicts, units),
        )
        self.last_response = response
        self._record(node, scope, response)
        from reviewkit.detectors import _response_to_signals

        return _response_to_signals(response, node_id, f"llm_{scope.value}", scope)

    def _verdicts(
        self,
        node_id: str,
        scope: ReviewScope,
        rules: list[Rule],
        units: dict[str, SourceUnit],
        function_ids: list[str],
    ) -> list[Verdict]:
        assert self.decision is not None
        assert self.pack is not None
        text = str(self.document.get_node_text(node_id) or "")
        covered = self.inner.state.covered()
        verdicts: list[Verdict] = []
        for rule in rules:
            unit = units.get(rule.function_id)
            answer, kind = self._decide_rule(
                rule=rule,
                unit=unit,
                text=text,
                covered=covered,
                function_ids=function_ids,
            )
            if kind is None or kind is VerdictKind.KEEP:
                continue
            if kind is VerdictKind.MISSING and (
                scope is not ReviewScope.DOCUMENT or covered.get(rule.function_id)
            ):
                continue
            verdicts.append(
                Verdict(
                    node_id=node_id,
                    kind=kind,
                    function_id=rule.function_id,
                    reason=answer.reason,
                    confidence=answer.confidence,
                )
            )
        return verdicts

    def _decide_rule(
        self,
        *,
        rule: Rule,
        unit: SourceUnit | None,
        text: str,
        covered: dict[str, list[str]],
        function_ids: list[str],
    ) -> tuple[DecisionAnswer, VerdictKind | None]:
        assert self.decision is not None
        assert self.pack is not None
        dumped = None if unit is None else unit.model_dump(mode="json")
        if rule.kind == "close" or rule.when == "function_absent":
            state: str | dict[str, Any] = {
                "covered": covered.get(rule.function_id, []),
                "candidate": rule.function_id,
                "unit": dumped,
            }
            questions: Mapping[str, Question] = document_present_question(
                function_label(self.pack, rule.function_id)
            )
            answers = self.decision.decide(state, questions)
            answer = coerce_answer(answers.get("present"))
            kind = VerdictKind.KEEP if is_noul_yes(answer) else VerdictKind.MISSING
            return answer, kind
        state = {"text": text, "tags": function_ids, "unit": dumped}
        answers = self.decision.decide(state, fragment_verdict_question())
        answer = coerce_answer(answers.get("verdict"))
        return answer, _verdict_kind(answer)

    def _findings(self, verdicts: list[Verdict]) -> list[ReviewFinding]:
        return [
            ReviewFinding(
                node_id=verdict.node_id,
                title=verdict.kind.value,
                description=verdict.reason or verdict.function_id,
            )
            for verdict in verdicts
            if verdict.kind is not VerdictKind.KEEP
        ]

    def _actions(
        self,
        node_id: str,
        scope: ReviewScope,
        verdicts: list[Verdict],
        units: dict[str, SourceUnit],
    ) -> list[ReviewAction]:
        floor = self.inner.profile.resolved_action_policy().min_confidence_for_auto_apply
        text = str(self.document.get_node_text(node_id) or "")
        actions: list[ReviewAction] = []
        for verdict in verdicts:
            if verdict.kind is VerdictKind.KEEP or verdict.kind not in _ACTION_TYPE:
                continue
            human = verdict.confidence < floor
            replacement = None
            if not human:
                written = self.inner._complete(
                    action_prompt(
                        self.inner.profile,
                        node_id=node_id,
                        text=text,
                        verdict=verdict,
                        unit=units.get(verdict.function_id),
                    ),
                    ActionText,
                )
                assert isinstance(written, ActionText)
                replacement = written.replacement_text
            actions.append(
                ReviewAction(
                    scope=scope,
                    action_type=_ACTION_TYPE[verdict.kind],
                    node_id=node_id,
                    original_text=text or None,
                    replacement_text=replacement,
                    reason=verdict.reason,
                    confidence=verdict.confidence,
                    requires_human_decision=human,
                    tags=[verdict.function_id],
                )
            )
        return actions

    def _record(self, node: DocNode | Any, scope: ReviewScope, response: Any) -> None:
        node_id = getattr(node, "id", "?")
        node_text = str(self.document.get_node_text(node_id) or "")
        self._enrich_response_lineage(response, node_id=node_id, scope=scope, node_text=node_text)
        self.effector.register_response(node_id, scope, response)

    def detect(self, node: DocNode | Any) -> list[RawSignal]:
        inner_node = getattr(node, "inner", node)
        effective_scope = self.scope
        if isinstance(inner_node, ReviewDocument):
            effective_scope = ReviewScope.DOCUMENT

        self.inner.lower_actions_for_prompt = _lower_actions_for_prompt(
            self.scope, inner_node, self._lower_actions
        )

        original_complete = self.inner._complete
        captured: dict[str, Any] = {"resp": None}

        def capturing_complete(messages: list[dict[str, str]], schema: type) -> Any:
            resp = original_complete(messages, schema)
            captured["resp"] = resp
            return resp

        self.inner._complete = capturing_complete  # type: ignore[method-assign]

        try:
            signals = self.inner.detect(node)
        finally:
            self.inner._complete = original_complete  # type: ignore[method-assign]
            self.inner.lower_actions_for_prompt = []

        resp = captured["resp"]
        self.last_response = resp
        if resp is not None:
            node_id = getattr(node, "id", getattr(inner_node, "id", "?"))
            node_text = str(
                self.document.get_node_text(node_id) or getattr(inner_node, "text", "") or ""
            )
            self._enrich_response_lineage(
                resp,
                node_id=node_id,
                scope=effective_scope,
                node_text=node_text,
            )
            self.effector.register_response(node_id, effective_scope, resp)

        return signals

    def reconcile(self, node: DocNode, request: Any, document_summary: str | None) -> Any:
        """Rereview one host-selected node; model output cannot redirect it."""
        inner_node = getattr(node, "inner", node)
        prompt = reconciliation_review_prompt(
            self.inner.profile,
            self.inner.state,
            cast(SentenceNode | ParagraphNode | SectionNode, inner_node),
            request,
            document_summary,
        )
        response = self.inner._complete(prompt, SentenceReviewResponse)
        target_text = str(self.document.get_node_text(node.id) or "")
        for finding in response.findings:
            finding.node_id = node.id
            if finding.dimension is None:
                finding.dimension = request.expected_dimension
            finding.metadata["reconciliation_request_id"] = request.request_id
        for action in response.actions:
            action.node_id = node.id
            action.scope = self.scope
            action.locator = ReviewLocator(
                node_id=node.id,
                char_start=0,
                char_end=len(target_text),
                original_text=target_text,
                text_hash=ReviewLocator.hash_text(target_text),
                node_hash=ReviewLocator.hash_text(target_text),
            )
        self._enrich_response_lineage(
            response,
            node_id=node.id,
            scope=self.scope,
            node_text=target_text,
        )
        for action in response.actions:
            if action.finding_id and any(
                finding.finding_id == action.finding_id
                and finding.reconciliation_disposition != ReconciliationDisposition.CONFLICT
                and finding.reconciles_finding_id
                for finding in response.findings
            ):
                match = next(
                    finding
                    for finding in response.findings
                    if finding.finding_id == action.finding_id
                )
                action.finding_id = match.reconciles_finding_id
        self.effector.register_response(node.id, self.scope, response)
        self.last_response = response
        return response

    def _enrich_response_lineage(
        self,
        response: Any,
        *,
        node_id: str,
        scope: ReviewScope,
        node_text: str,
    ) -> None:
        """Attach host source lineage before response actions receive policy events."""
        profile_digest = hashlib.sha256(
            json.dumps(
                self.inner.profile.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        source_locator = ReviewLocator(
            node_id=node_id,
            char_start=0,
            char_end=len(node_text),
            original_text=node_text,
            text_hash=ReviewLocator.hash_text(node_text),
            node_hash=ReviewLocator.hash_text(node_text),
        )
        for finding in response.findings:
            parents = tuple(
                event.event_id
                for existing in self.inner.state.findings
                if existing.finding_id == finding.finding_id
                for event in existing.lineage
            )
            evidence_refs = tuple(
                _stable_evidence_ref(finding.finding_id, index, evidence)
                for index, evidence in enumerate(finding.evidence)
            )
            event = FindingLineageEvent(
                kind="synthesis" if parents else "source",
                scope=scope,
                node_id=node_id,
                locator=source_locator,
                source_digest=ReviewLocator.hash_text(node_text),
                parent_event_ids=parents,
                evidence_refs=evidence_refs,
                detector=type(self.inner).__name__,
                model=type(self.inner.llm).__name__,
                profile_digest=profile_digest,
            )
            finding.lineage = (*finding.lineage, event)

        finding_events = {finding.finding_id: finding.lineage for finding in response.findings}
        for existing in self.inner.state.findings:
            finding_events[existing.finding_id] = existing.lineage
            for alias in existing.metadata.get("merged_finding_ids", []):
                finding_events[alias] = existing.lineage
        for action in response.actions:
            if action.finding_id in finding_events:
                action.lineage = tuple(finding_events[action.finding_id])
            elif action.finding_id is None:
                action.lineage = (
                    FindingLineageEvent(
                        kind="source",
                        scope=scope,
                        node_id=node_id,
                        locator=source_locator,
                        source_digest=ReviewLocator.hash_text(node_text),
                        evidence_refs=tuple(
                            _stable_evidence_ref(action.id, index, evidence)
                            for index, evidence in enumerate(action.evidence_refs)
                        ),
                        detector=type(self.inner).__name__,
                        model=type(self.inner.llm).__name__,
                        profile_digest=profile_digest,
                        action_id=action.id,
                    ),
                )

    def signals_for_response(self, response: Any, node_id: str) -> list[RawSignal]:
        from reviewkit.detectors import _response_to_signals

        return _response_to_signals(response, node_id, "llm_reconciliation", self.scope)


def _stable_evidence_ref(finding_id: str, index: int, evidence: Any) -> str:
    payload = evidence.model_dump(mode="json") if hasattr(evidence, "model_dump") else evidence
    digest = hashlib.sha256(
        json.dumps([finding_id, index, payload], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"evidence-{digest}"


__all__ = ["TaktReviewer"]

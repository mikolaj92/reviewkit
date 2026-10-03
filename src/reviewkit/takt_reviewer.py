"""Takt v0.3.2-based hierarchical review orchestration for ReviewKit.

A review always receives a Pack, a DecisionClient, and an LLMClient.

1. Name every enabled node (tags only). No cascade, no effector, tags are not
   ``RawSignal``.
2. Judge matching rules → findings → signals → takt → effector. Covered and
   unmatched nodes short-circuit before evaluate.
3. Optional act through ``LLMClient.complete_json`` only for change / delete /
   insert at or above the confidence floor. ``missing`` is a finding, not a write.

There is no ``pack=None`` fused ``complete_json`` of findings+actions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from reviewkit.actions import demote_cross_scope_overlaps, prepare_actions
from reviewkit.context import EmptyReviewContextProvider, ReviewContextProvider
from reviewkit.decision import (
    DecisionAnswer,
    DecisionAnswers,
    DecisionClient,
    DecisionState,
    DocumentDecisionState,
    FragmentDecisionState,
    Question,
    RawDecisionAnswer,
    coerce_answer,
    document_present_question,
    fragment_verdict_question,
    is_noul_yes,
    naming_questions,
)
from reviewkit.detectors import BaseLLMDetector, _response_to_signals
from reviewkit.document import ReviewDocument
from reviewkit.effectors import ReviewEffector
from reviewkit.homeostat import build_layer_specs, scope_to_layer_index
from reviewkit.llm import LLMClient, LLMClientError, LLMClientFailure
from reviewkit.models import (
    DocumentReviewResponse,
    FindingLineageEvent,
    ParagraphReviewResponse,
    ReviewAction,
    ReviewActionType,
    ReviewBoundError,
    ReviewFailureClass,
    ReviewFinding,
    ReviewLocator,
    ReviewResponse,
    ReviewResult,
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
from reviewkit.prompts import action_prompt
from reviewkit.review_bounds import (
    bound_document_sections,
    build_document_source_context,
)
from reviewkit.state import ReviewState
from reviewkit.takt_client import TaktClient
from reviewkit.takt_types import LayerSpec, RawSignal

type ReviewPrior = (
    ReviewResult | tuple[Sequence[ReviewFinding], Sequence[ReviewAction], ReviewState] | None
)

_ACTION_TYPE = {
    VerdictKind.CHANGE: ReviewActionType.REPLACE_TEXT,
    VerdictKind.DELETE: ReviewActionType.DELETE_TEXT,
    VerdictKind.INSERT: ReviewActionType.INSERT_TEXT,
}
_ACT_KINDS = frozenset(_ACTION_TYPE)

_RESPONSE_SCHEMA: dict[ReviewScope, type[ReviewResponse]] = {
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
        pack: Pack,
        decision: DecisionClient,
        context_provider: ReviewContextProvider | None = None,
        action_policy: ActionPolicy | None = None,
        *,
        takt_client: TaktClient | None = None,
    ) -> None:
        self.profile = profile
        self.llm = llm
        self.pack = pack
        self.decision = decision
        self.context_provider = context_provider or EmptyReviewContextProvider()
        self.action_policy = action_policy
        self.state = ReviewState()
        self.takt_client = takt_client or TaktClient()
        self.traces: list[PassTrace] = []

    def review(
        self,
        document: ReviewDocument,
        *,
        prior: ReviewPrior = None,
        level: ReviewScope | str | None = None,
        passes: int = 1,
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        """Name, then judge. With no ``prior`` and no ``level`` this is today's walk.

        ``level`` selects one unit size. That call names and judges only those
        units. Call the same level again with ``prior`` to continue, or a
        different ``level`` when the caller is ready to move. ``prior`` is a
        previous return value (or a ``ReviewResult``). ``passes`` is only a
        convenience loop over the same level (or today's full walk when
        ``level`` is omitted).
        """
        if passes < 1:
            raise ValueError("passes must be >= 1")
        scope = _coerce_level(level)
        _require_level(self.profile.review_pipeline, scope)
        result = self._review_once(document, prior=prior, level=scope)
        for _ in range(passes - 1):
            result = self._review_once(document, prior=result, level=scope)
        return result

    def _review_once(
        self,
        document: ReviewDocument,
        *,
        prior: ReviewPrior,
        level: ReviewScope | None,
    ) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState]:
        prior_findings, prior_actions, prior_state = _unpack_prior(prior)
        source_document = document
        document = bound_document_sections(document, self.profile.section_char_budget)
        enabled = _enabled_scopes(self.profile.review_pipeline, level)
        document_source_context = None
        if ReviewScope.DOCUMENT in enabled:
            document_source_context = build_document_source_context(
                source_document,
                self.profile.document_source_char_budget,
            )
        state = prior_state.model_copy(deep=True) if prior_state is not None else ReviewState()
        if prior_findings and not state.findings:
            state.findings = [finding.model_copy(deep=True) for finding in prior_findings]
        self.state = state
        self.traces = []
        effector = ReviewEffector(state)
        effector.findings = list(state.findings)

        layers = build_layer_specs(self.profile)
        layer_by_scope = scope_to_layer_index(self.profile)
        plant = ReviewDocumentPlant(document, scope_layers=layer_by_scope)

        detectors = self._build_detectors(
            document,
            state,
            effector,
            enabled,
            document_source_context=document_source_context,
        )

        self._name(plant, enabled)
        feedback = prior is not None
        self._judge_pass(
            plant,
            detectors,
            layers,
            enabled,
            effector,
            labels_by_node=_labels_by_node(state) if feedback else None,
            comments_by_node=_comments_by_node(prior_actions) if feedback else None,
        )

        prepared_new = prepare_actions(
            document, self.profile, effector.actions, policy=self.action_policy
        )
        combined = list(prior_actions) + prepared_new
        final_actions = demote_cross_scope_overlaps(document, combined)

        deduped_findings: list[ReviewFinding] = []
        seen: dict[str, bool] = {}
        for f in effector.findings:
            key = f.finding_id or (f.title + "|" + f.node_id)
            if key not in seen:
                seen[key] = True
                deduped_findings.append(f)

        return deduped_findings, final_actions, state

    def _judge_pass(
        self,
        plant: ReviewDocumentPlant,
        detectors: dict[ReviewScope, _LLMDetectorAdapter],
        layers: list[LayerSpec],
        enabled: set[ReviewScope],
        effector: ReviewEffector,
        *,
        labels_by_node: dict[str, list[str]] | None = None,
        comments_by_node: dict[str, list[str]] | None = None,
    ) -> None:
        for node in plant.sequential_scan():
            scope = node.scope()
            if scope is None or scope not in enabled:
                continue
            function_ids, comments = _pass_input(node, labels_by_node, comments_by_node)
            detector = detectors[scope]
            signals = detector.judge(node, function_ids=function_ids, comments=comments)
            if not signals:
                continue
            decision = self.takt_client.evaluate(
                plant_nodes=[node.to_plant_node(value=0.0)],
                layers=layers,
                raw_signals=signals,
            )
            detector.act_after_judge(node)
            effector.apply_takt_decision(node.id, decision)

    def _name(self, plant: ReviewDocumentPlant, enabled: set[ReviewScope]) -> None:
        """First scan. Tags only: no cascade evaluation and no effector."""
        named: list[FunctionTag] = []
        for node in plant.sequential_scan():
            scope = node.scope()
            if scope is None or scope not in enabled:
                continue
            inner = getattr(node, "inner", node)
            text = str(getattr(inner, "text", "") or "")
            if not text.strip():
                continue
            functions = naming_functions(self.pack, scope)
            if not functions:
                continue
            questions = naming_questions(functions)
            answers = _plugin_decide(self.decision, text, questions, node_id=node.id)
            tagged = [
                function_id
                for function_id, raw in answers.items()
                if function_id in questions and is_noul_yes(_plugin_coerce(raw, node.id))
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
                named.append(tag)
        self.state.tags = _merge_tags(self.state.tags, named)

    def _build_detectors(
        self,
        document: ReviewDocument,
        state: ReviewState,
        effector: ReviewEffector,
        enabled: set[ReviewScope],
        *,
        document_source_context: dict[str, Any] | None = None,
    ) -> dict[ReviewScope, _LLMDetectorAdapter]:
        detectors: dict[ReviewScope, _LLMDetectorAdapter] = {}
        for scope in self.profile.review_pipeline:
            if scope not in enabled:
                continue
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
        pack: Pack,
        decision: DecisionClient,
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
        self.last_response: ReviewResponse | None = None
        self._pending_verdicts: list[Verdict] = []
        self._pending_units: dict[str, SourceUnit] = {}
        self._pending_scope: ReviewScope = scope

    def judge(
        self,
        node: DocNode,
        *,
        function_ids: list[str] | None = None,
        comments: Sequence[str] = (),
    ) -> list[RawSignal]:
        """Second scan. Matched rules and the single unit each one cites."""
        inner_node = getattr(node, "inner", node)
        effective_scope = self.scope
        if isinstance(inner_node, ReviewDocument):
            effective_scope = ReviewScope.DOCUMENT
        return self._judge_with_pack(
            node, effective_scope, function_ids=function_ids, comments=comments
        )

    def _judge_with_pack(
        self,
        node: DocNode,
        scope: ReviewScope,
        *,
        function_ids: list[str] | None = None,
        comments: Sequence[str] = (),
    ) -> list[RawSignal]:
        """Second scan. Findings and signals only; the effector does not write yet."""
        self._pending_verdicts = []
        self._pending_units = {}
        self._pending_scope = scope
        self.last_response = None
        node_id = getattr(node, "id", "?")
        tagged = (
            list(function_ids)
            if function_ids is not None
            else self.inner.state.functions_for(node_id)
        )
        covered = self.inner.state.covered()
        rules = judge_rules(self.pack, scope, tagged, covered)
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
            if (unit := cited_unit(self.pack, rule.source_unit_id)) is not None
        }
        verdicts = self._verdicts(node_id, scope, rules, units, tagged, comments)
        if not verdicts:
            return []
        response = _RESPONSE_SCHEMA[scope](
            findings=self._findings(verdicts),
            actions=[],
        )
        self._pending_verdicts = verdicts
        self._pending_units = units
        self.last_response = response
        self._record(node, scope, response)
        return _response_to_signals(response, node_id, f"llm_{scope.value}", scope)

    def act_after_judge(self, node: DocNode) -> None:
        """Optional write: change/delete/insert at or above the confidence floor."""
        response = self.last_response
        if response is None or not self._pending_verdicts:
            return
        node_id = getattr(node, "id", "?")
        actions = self._actions(
            node_id, self._pending_scope, self._pending_verdicts, self._pending_units
        )
        if not actions:
            return
        response.actions.extend(actions)
        node_text = str(self.document.get_node_text(node_id) or "")
        self._attach_action_lineage(
            response, node_id=node_id, scope=self._pending_scope, node_text=node_text
        )

    def _verdicts(
        self,
        node_id: str,
        scope: ReviewScope,
        rules: list[Rule],
        units: dict[str, SourceUnit],
        function_ids: list[str],
        comments: Sequence[str] = (),
    ) -> list[Verdict]:
        text = str(self.document.get_node_text(node_id) or "")
        covered = self.inner.state.covered()
        verdicts: list[Verdict] = []
        for rule in rules:
            unit = units.get(rule.function_id)
            answer, kind = self._decide_rule(
                node_id=node_id,
                rule=rule,
                unit=unit,
                text=text,
                covered=covered,
                function_ids=function_ids,
                comments=comments,
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
        node_id: str,
        rule: Rule,
        unit: SourceUnit | None,
        text: str,
        covered: dict[str, list[str]],
        function_ids: list[str],
        comments: Sequence[str] = (),
    ) -> tuple[DecisionAnswer, VerdictKind | None]:
        if rule.kind == "close" or rule.when == "function_absent":
            state = DocumentDecisionState(
                covered=covered.get(rule.function_id, []),
                candidate=rule.function_id,
                unit=unit,
                comments=list(comments),
            )
            questions: Mapping[str, Question] = document_present_question(
                function_label(self.pack, rule.function_id)
            )
            answers = _plugin_decide(self.decision, state, questions, node_id=node_id)
            answer = _plugin_coerce(answers.get("present"), node_id)
            kind = VerdictKind.KEEP if is_noul_yes(answer) else VerdictKind.MISSING
            return answer, kind
        fragment_state = FragmentDecisionState(
            text=text,
            tags=function_ids,
            unit=unit,
            comments=list(comments),
        )
        answers = _plugin_decide(
            self.decision, fragment_state, fragment_verdict_question(), node_id=node_id
        )
        answer = _plugin_coerce(answers.get("verdict"), node_id)
        return answer, _verdict_kind(answer)

    def _findings(self, verdicts: list[Verdict]) -> list[ReviewFinding]:
        return [
            ReviewFinding(
                node_id=verdict.node_id,
                title=verdict.kind.value,
                description=verdict.reason or verdict.function_id,
                confidence=verdict.confidence,
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
        self.inner._active_node_id = node_id
        for verdict in verdicts:
            if verdict.kind not in _ACT_KINDS:
                continue
            human = verdict.confidence < floor
            replacement = None
            if not human:
                replacement, human = self._replacement_text(
                    node_id, text, verdict, units.get(verdict.function_id)
                )
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

    def _replacement_text(
        self,
        node_id: str,
        text: str,
        verdict: Verdict,
        unit: SourceUnit | None,
    ) -> tuple[str | None, bool]:
        """Write replacement text, or degrade to a person on plugin failure."""
        try:
            written = self.inner._complete(
                action_prompt(
                    self.inner.profile,
                    node_id=node_id,
                    text=text,
                    verdict=verdict,
                    unit=unit,
                ),
                ActionText,
            )
        except (ReviewBoundError, LLMClientError, TimeoutError, ValidationError) as exc:
            bound = _plugin_bound_error(exc, node_id)
            self.traces.append(
                PassTrace(
                    checks=(
                        ProcessCheck(
                            name="act_plugin_failed",
                            passed=False,
                            detail=bound.failure_class.value,
                        ),
                    )
                )
            )
            self.inner.state.warnings.append(
                f"Action write failed for node {node_id}: plugin_failure"
            )
            return None, True
        assert isinstance(written, ActionText)
        return written.replacement_text, False

    def _record(self, node: DocNode, scope: ReviewScope, response: ReviewResponse) -> None:
        node_id = getattr(node, "id", "?")
        node_text = str(self.document.get_node_text(node_id) or "")
        self._enrich_response_lineage(response, node_id=node_id, scope=scope, node_text=node_text)
        self.effector.register_response(node_id, scope, response)

    def _enrich_response_lineage(
        self,
        response: ReviewResponse,
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

        self._attach_action_lineage(response, node_id=node_id, scope=scope, node_text=node_text)

    def _attach_action_lineage(
        self,
        response: Any,
        *,
        node_id: str,
        scope: ReviewScope,
        node_text: str,
    ) -> None:
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
        finding_events = {finding.finding_id: finding.lineage for finding in response.findings}
        for existing in self.inner.state.findings:
            finding_events[existing.finding_id] = existing.lineage
            for alias in existing.metadata.get("merged_finding_ids", []):
                finding_events[alias] = existing.lineage
        for action in response.actions:
            if action.lineage:
                continue
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


def _plugin_bound_error(exc: BaseException, node_id: str) -> ReviewBoundError:
    """Map a host plugin failure to a content-free structured bound."""
    if isinstance(exc, ReviewBoundError):
        return exc
    if isinstance(exc, TimeoutError):
        return ReviewBoundError(
            failure_class=ReviewFailureClass.TIMEOUT,
            node_id=node_id,
            reason="plugin_failure",
        )
    if isinstance(exc, LLMClientError):
        failure_class = {
            LLMClientFailure.TIMEOUT: ReviewFailureClass.TIMEOUT,
            LLMClientFailure.RESPONSE_SCHEMA: ReviewFailureClass.SCHEMA_MISMATCH,
            LLMClientFailure.TRANSPORT: ReviewFailureClass.UNSUPPORTED_SHAPE,
        }[exc.failure]
        return ReviewBoundError(
            failure_class=failure_class,
            node_id=node_id,
            reason="plugin_failure",
        )
    if isinstance(exc, ValidationError):
        return ReviewBoundError(
            failure_class=ReviewFailureClass.SCHEMA_MISMATCH,
            node_id=node_id,
            reason="plugin_failure",
        )
    return ReviewBoundError(
        failure_class=ReviewFailureClass.UNSUPPORTED_SHAPE,
        node_id=node_id,
        reason="plugin_failure",
    )


def _plugin_decide(
    client: DecisionClient,
    state: DecisionState,
    questions: Mapping[str, Question],
    *,
    node_id: str,
) -> DecisionAnswers:
    try:
        return client.decide(state, questions)
    except Exception as exc:
        raise _plugin_bound_error(exc, node_id) from exc


def _plugin_coerce(raw: RawDecisionAnswer | None, node_id: str) -> DecisionAnswer:
    try:
        return coerce_answer(raw)
    except (ValidationError, ValueError, TypeError) as exc:
        raise _plugin_bound_error(exc, node_id) from exc


def _stable_evidence_ref(finding_id: str, index: int, evidence: object) -> str:
    payload = evidence.model_dump(mode="json") if hasattr(evidence, "model_dump") else evidence
    digest = hashlib.sha256(
        json.dumps([finding_id, index, payload], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"evidence-{digest}"


def _coerce_level(level: ReviewScope | str | None) -> ReviewScope | None:
    if level is None:
        return None
    return ReviewScope(level)


def _require_level(pipeline: Sequence[ReviewScope], level: ReviewScope | None) -> None:
    if level is not None and level not in pipeline:
        raise ValueError(f"level {level.value!r} is not in review_pipeline")


def _enabled_scopes(pipeline: Sequence[ReviewScope], level: ReviewScope | None) -> set[ReviewScope]:
    if level is None:
        return set(pipeline)
    return {level}


def _unpack_prior(
    prior: ReviewPrior,
) -> tuple[list[ReviewFinding], list[ReviewAction], ReviewState | None]:
    if prior is None:
        return [], [], None
    if isinstance(prior, ReviewResult):
        return list(prior.findings), list(prior.actions), prior.state
    findings, actions, state = prior
    return list(findings), list(actions), state


def _merge_tags(
    existing: Sequence[FunctionTag], incoming: Sequence[FunctionTag]
) -> list[FunctionTag]:
    function_ids: dict[str, list[str]] = {}
    order: list[str] = []
    for tag in (*existing, *incoming):
        if tag.node_id not in function_ids:
            order.append(tag.node_id)
            function_ids[tag.node_id] = []
        for function_id in tag.function_ids:
            if function_id not in function_ids[tag.node_id]:
                function_ids[tag.node_id].append(function_id)
    return [
        FunctionTag(node_id=node_id, function_ids=function_ids[node_id])
        for node_id in order
        if function_ids[node_id]
    ]


def _comment_text(action: ReviewAction) -> str:
    return (action.comment or action.reason or "").strip()


def _labels_by_node(state: ReviewState) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for tag in state.tags:
        found[tag.node_id] = list(tag.function_ids)
    return found


def _comments_by_node(actions: Sequence[ReviewAction]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for action in actions:
        text = _comment_text(action)
        if not text:
            continue
        bucket = found.setdefault(action.node_id, [])
        if text not in bucket:
            bucket.append(text)
    return found


def _pass_input(
    node: DocNode,
    labels_by_node: dict[str, list[str]] | None,
    comments_by_node: dict[str, list[str]] | None,
) -> tuple[list[str] | None, tuple[str, ...]]:
    """Own and contained comments/labels from a previous invocation."""
    if labels_by_node is None or comments_by_node is None:
        return None, ()
    labels: list[str] = []
    seen_labels: set[str] = set()
    comments: list[str] = []
    seen_comments: set[str] = set()
    for node_id in [node.id, *node.descendant_ids()]:
        for label in labels_by_node.get(node_id, ()):
            if label not in seen_labels:
                seen_labels.add(label)
                labels.append(label)
        for comment in comments_by_node.get(node_id, ()):
            if comment not in seen_comments:
                seen_comments.add(comment)
                comments.append(comment)
    return labels, tuple(comments)


__all__ = ["ReviewPrior", "TaktReviewer"]

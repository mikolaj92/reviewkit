"""Two-scan TaktReviewer edge cases: empty pack, covered skip, act, plugins."""

from __future__ import annotations

import json

import pytest

from reviewkit.decision import MockDecisionClient
from reviewkit.effectors import ReviewEffector
from reviewkit.llm import LLMClientError, LLMClientFailure, MockLLMClient
from reviewkit.models import ReviewBoundError, ReviewFailureClass
from reviewkit.pack import Function, Ontology, Pack, Rule, SourceUnit
from reviewkit.parser_text import parse_text
from reviewkit.profile import ReviewProfile
from reviewkit.review import review_tree
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import TaktDecision

_FUNCTIONS = ("lead", "claim")


def _profile() -> ReviewProfile:
    return ReviewProfile(
        name="notice",
        language="en",
        document_type="notice",
        reviewer_role="reviewer",
    )


def _named(*yes: str) -> dict[str, bool]:
    return {function_id: function_id in yes for function_id in _FUNCTIONS}


def _function(function_id: str) -> Function:
    return Function(id=function_id, label=function_id.replace("_", " "), attach_to=["sentence"])


def _pack(*, rules: list[Rule] | None = None, units: dict[str, SourceUnit] | None = None) -> Pack:
    return Pack(
        ontology=Ontology(functions=[_function(item) for item in _FUNCTIONS]),
        units={} if units is None else units,
        rules=[] if rules is None else rules,
    )


def _defect_and_close() -> Pack:
    return _pack(
        units={
            "unit-lead": SourceUnit(
                id="unit-lead",
                source_id="source",
                locator="§1",
                text="lead source",
                force="binding",
            )
        },
        rules=[
            Rule(
                id="defect-lead",
                kind="defect",
                function_id="lead",
                scope="fragment",
                when="function_present",
            ),
            Rule(
                id="close-claim",
                kind="close",
                function_id="claim",
                scope="document",
                when="function_absent",
                source_unit_id="unit-lead",
            ),
        ],
    )


class _RecordingTakt:
    def __init__(self, outcome: str = "stable") -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    def evaluate(self, **kwargs) -> TaktDecision:
        self.calls.append(kwargs)
        node_id = kwargs["plant_nodes"][0].id
        return TaktDecision(outcome=self.outcome, node_id=node_id)  # type: ignore[arg-type]


class _StickyDecision:
    """Idempotent plugin: same answers every call, no popped script."""

    def decide(self, state, questions):
        if "verdict" in questions:
            return {"verdict": "keep"}
        if "present" in questions:
            return {"present": True}
        return {key: True for key in questions}


class _BoomDecision:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def decide(self, state, questions):
        raise self.exc


def _reviewer(
    llm: MockLLMClient,
    pack: Pack,
    decision: object | None = None,
    *,
    takt: object | None = None,
) -> TaktReviewer:
    return TaktReviewer(
        profile=_profile(),
        llm=llm,
        pack=pack,
        decision=decision,  # type: ignore[arg-type]
        takt_client=takt or _RecordingTakt(),  # type: ignore[arg-type]
    )


def _payload(call) -> dict:
    return json.loads(call.messages[1]["content"].split("\n\n", 1)[1])


def test_empty_rules_pack_names_and_skips_judge_takt_and_act() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(answers=[_named("lead")] * 8)
    takt = _RecordingTakt()
    llm = MockLLMClient(responses=[{"replacement_text": "should not write"}])

    findings, actions, state = _reviewer(llm, _pack(), decision, takt=takt).review(document)

    assert "lead" in state.covered()
    assert findings == []
    assert actions == []
    assert takt.calls == []
    assert llm.calls == []
    assert not any(
        "verdict" in call.questions or "present" in call.questions for call in decision.calls
    )


def test_empty_units_still_judge_rules_that_cite_none() -> None:
    document = parse_text("A lead sentence.")
    pack = _pack(
        units={},
        rules=[
            Rule(
                id="defect-lead",
                kind="defect",
                function_id="lead",
                scope="fragment",
                when="function_present",
            )
        ],
    )
    decision = MockDecisionClient(
        answers=[_named("lead"), _named(), _named(), _named(), {"verdict": "keep"}]
    )
    findings, actions, state = _reviewer(MockLLMClient(), pack, decision).review(document)

    assert state.covered() == {"lead": ["p1.s1"]}
    fragment = next(call for call in decision.calls if "verdict" in call.questions)
    assert fragment.state.unit is None
    assert findings == []
    assert actions == []


def test_covered_document_skips_close_questions_and_takt() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[
            _named("lead", "claim"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
        ]
    )
    takt = _RecordingTakt()

    findings, actions, state = _reviewer(
        MockLLMClient(), _defect_and_close(), decision, takt=takt
    ).review(document)

    assert set(state.covered()) == {"lead", "claim"}
    assert findings == []
    assert actions == []
    assert takt.calls == []
    assert not any("present" in call.questions for call in decision.calls)


def test_judge_with_no_tags_skips_fragment_verdicts() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[_named(), _named(), _named(), _named(), {"present": False}]
    )
    takt = _RecordingTakt()

    findings, _actions, state = _reviewer(
        MockLLMClient(), _defect_and_close(), decision, takt=takt
    ).review(document)

    assert state.covered() == {}
    assert not any("verdict" in call.questions for call in decision.calls)
    assert [call.questions for call in decision.calls if "present" in call.questions]
    assert [finding.title for finding in findings] == ["missing"]
    assert findings[0].description == "claim"
    assert takt.calls
    assert takt.calls[0]["plant_nodes"][0].id == "document"


def test_missing_does_not_call_the_act_plugin() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[
            _named("lead"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
            {"present": False},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "must not write"}])

    findings, actions, _state = _reviewer(llm, _defect_and_close(), decision).review(document)

    assert [finding.title for finding in findings] == ["missing"]
    assert actions == []
    assert llm.calls == []


def test_act_skipped_below_confidence_does_not_call_llm() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[
            _named("lead", "claim"),
            _named(),
            _named(),
            _named(),
            {"verdict": {"value": "change", "confidence": 0.2}},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "must not write"}])
    takt = _RecordingTakt()

    _findings, actions, _state = _reviewer(llm, _defect_and_close(), decision, takt=takt).review(
        document
    )

    assert actions[0].requires_human_decision is True
    assert actions[0].replacement_text is None
    assert llm.calls == []
    assert takt.calls


def test_act_runs_only_for_change_above_confidence() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[
            _named("lead", "claim"),
            _named(),
            _named(),
            _named(),
            {"verdict": {"value": "change", "confidence": 0.95}},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "rewritten lead"}])

    findings, actions, _state = _reviewer(llm, _defect_and_close(), decision).review(document)

    assert [finding.title for finding in findings] == ["change"]
    assert actions[0].replacement_text == "rewritten lead"
    assert actions[0].requires_human_decision is False
    assert _payload(llm.calls[0])["pass"] == "action"
    assert _payload(llm.calls[0])["verdict"]["kind"] == "change"


def test_name_does_not_register_with_the_effector(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[str] = []
    original = ReviewEffector.register_response

    def tracking(self, node_id, scope, response):  # type: ignore[no-untyped-def]
        registered.append(node_id)
        return original(self, node_id, scope, response)

    monkeypatch.setattr(ReviewEffector, "register_response", tracking)
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(answers=[_named("lead")] * 8)

    _reviewer(MockLLMClient(), _pack(), decision).review(document)

    assert registered == []


def test_plugin_failure_during_name_is_a_structured_bound() -> None:
    document = parse_text("A lead sentence.")
    with pytest.raises(ReviewBoundError) as caught:
        _reviewer(
            MockLLMClient(),
            _pack(),
            _BoomDecision(LLMClientError(LLMClientFailure.TIMEOUT, reason_code="deadline")),
        ).review(document)
    assert caught.value.failure_class is ReviewFailureClass.TIMEOUT
    assert caught.value.reason == "plugin_failure"
    assert caught.value.node_id == "p1.s1"


def test_plugin_failure_during_judge_is_a_structured_bound() -> None:
    document = parse_text("A lead sentence.")
    named = _StickyDecision()

    class _NameThenBoom:
        def decide(self, state, questions):
            if "verdict" in questions or "present" in questions:
                raise LLMClientError(LLMClientFailure.RESPONSE_SCHEMA, reason_code="shape")
            return named.decide(state, questions)

    with pytest.raises(ReviewBoundError) as caught:
        _reviewer(MockLLMClient(), _defect_and_close(), _NameThenBoom()).review(document)
    assert caught.value.failure_class is ReviewFailureClass.SCHEMA_MISMATCH
    assert caught.value.reason == "plugin_failure"


def test_act_plugin_failure_degrades_to_a_person() -> None:
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[
            _named("lead", "claim"),
            _named(),
            _named(),
            _named(),
            {"verdict": {"value": "change", "confidence": 0.95}},
        ]
    )
    llm = MockLLMClient(responses=[LLMClientError(LLMClientFailure.TRANSPORT, reason_code="down")])
    reviewer = _reviewer(llm, _defect_and_close(), decision)
    findings, actions, state = reviewer.review(document)

    assert [finding.title for finding in findings] == ["change"]
    assert actions[0].requires_human_decision is True
    assert actions[0].replacement_text is None
    assert any("plugin_failure" in warning for warning in state.warnings)
    failed = [
        check
        for trace in reviewer.traces
        for check in trace.checks
        if check.name == "act_plugin_failed"
    ]
    assert failed and failed[0].passed is False


def test_rerun_resets_traces_and_tags() -> None:
    document = parse_text("A lead sentence.")
    reviewer = _reviewer(MockLLMClient(), _pack(), _StickyDecision())
    _findings_a, _actions_a, state_a = reviewer.review(document)
    traces_once = len(reviewer.traces)
    tags_once = list(state_a.tags)
    _findings_b, _actions_b, state_b = reviewer.review(document)

    assert len(reviewer.traces) == traces_once
    assert list(state_b.tags) == tags_once
    assert state_b.covered() == state_a.covered()


def test_review_tree_entry_forwards_pack_and_skips_act_on_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reviewkit.takt_reviewer.TaktClient", _RecordingTakt)
    document = parse_text("A lead sentence.")
    decision = MockDecisionClient(
        answers=[
            _named("lead"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
            {"present": False},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "must not write"}])

    result = review_tree(document, _profile(), llm, pack=_defect_and_close(), decision=decision)

    assert [finding.title for finding in result.findings] == ["missing"]
    assert result.actions == []
    assert llm.calls == []

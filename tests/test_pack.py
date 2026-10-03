import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from reviewkit.decision import (
    DocumentDecisionState,
    FragmentDecisionState,
    MockDecisionClient,
    NoulQuestion,
)
from reviewkit.llm import MockLLMClient
from reviewkit.models import ReviewResponse, ReviewScope
from reviewkit.pack import (
    Function,
    FunctionTag,
    NamingResponse,
    Ontology,
    Pack,
    Rule,
    SourceUnit,
    accepted_tags,
    check_naming,
    cited_unit,
    judge_rules,
    naming_functions,
)
from reviewkit.parser_text import parse_text
from reviewkit.profile import ReviewProfile
from reviewkit.review import review_tree
from reviewkit.state import ReviewState
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import RawSignal, TaktDecision

_FUNCTIONS = ("controller_identity", "purposes")
_PACK_FIXTURE = Path(__file__).parent / "fixtures" / "notice.pack.json"


def _profile() -> ReviewProfile:
    return ReviewProfile(
        name="notice",
        language="pl",
        document_type="privacy_notice",
        reviewer_role="reviewer",
    )


def _named(*yes: str) -> dict[str, bool]:
    return {function_id: function_id in yes for function_id in _FUNCTIONS}


def _pack() -> Pack:
    return Pack.model_validate_json(_PACK_FIXTURE.read_text(encoding="utf-8"))


def _payload(call) -> dict:
    return json.loads(call.messages[1]["content"].split("\n\n", 1)[1])


def _dump(value: object) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _naming_calls(decision: MockDecisionClient) -> list:
    return [
        call
        for call in decision.calls
        if "verdict" not in call.questions and "present" not in call.questions
    ]


class _Stable:
    def evaluate(self, **kwargs) -> TaktDecision:
        return TaktDecision(outcome="stable", node_id="n")


class _RecordingTakt:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.calls: list[dict] = []

    def evaluate(self, **kwargs) -> TaktDecision:
        self.events.append("evaluate")
        self.calls.append(kwargs)
        nodes = kwargs.get("plant_nodes") or ()
        node_id = nodes[0].id if nodes else "n"
        return TaktDecision(outcome="stable", node_id=node_id)


class _OrderedDecision(MockDecisionClient):
    def __init__(self, events: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self.events = events

    def decide(self, state, questions):
        self.events.append("decide")
        return super().decide(state, questions)


def _reviewer(
    llm: MockLLMClient,
    pack: Pack,
    decision: MockDecisionClient,
    takt_client=None,
) -> TaktReviewer:
    return TaktReviewer(
        profile=_profile(),
        llm=llm,
        pack=pack,
        decision=decision,
        takt_client=takt_client or _Stable(),
    )


def test_pack_rejects_a_rule_that_cites_an_unknown_function() -> None:
    with pytest.raises(ValidationError):
        Pack(
            ontology=Ontology(
                functions=[Function(id="cookies", label="Cookies", attach_to=["sentence"])]
            ),
            units={},
            rules=[
                Rule(
                    id="label",
                    kind="label",
                    function_id="controller_identity",
                    scope="fragment",
                    when="always",
                )
            ],
        )


def test_pack_rejects_a_rule_that_cites_an_unknown_unit() -> None:
    with pytest.raises(ValidationError):
        Pack(
            ontology=Ontology(
                functions=[Function(id="cookies", label="Cookies", attach_to=["sentence"])]
            ),
            units={},
            rules=[
                Rule(
                    id="close",
                    kind="close",
                    function_id="cookies",
                    scope="document",
                    when="function_absent",
                    source_unit_id="missing-unit",
                ),
            ],
        )


def test_pack_rejects_a_close_rule_on_a_fragment() -> None:
    with pytest.raises(ValidationError):
        Pack(
            ontology=Ontology(
                functions=[Function(id="cookies", label="Cookies", attach_to=["sentence"])]
            ),
            units={},
            rules=[
                Rule(
                    id="close",
                    kind="close",
                    function_id="cookies",
                    scope="fragment",
                    when="function_absent",
                )
            ],
        )


def test_source_unit_uses_force_not_status() -> None:
    with pytest.raises(ValidationError):
        SourceUnit.model_validate(
            {
                "id": "u",
                "source_id": "s",
                "locator": "§1",
                "force": "binding",
                "status": "binding",
            }
        )


def test_naming_response_carries_only_tags() -> None:
    assert list(NamingResponse.model_fields) == ["tags"]
    with pytest.raises(ValidationError):
        NamingResponse.model_validate({"tags": [], "findings": [], "actions": []})


def test_covered_maps_function_ids_to_node_ids() -> None:
    state = ReviewState(
        tags=[
            FunctionTag(node_id="p1.s1", function_ids=["lead"]),
            FunctionTag(node_id="p1.s2", function_ids=["lead", "numeric_claim"]),
        ]
    )
    assert state.covered() == {"lead": ["p1.s1", "p1.s2"], "numeric_claim": ["p1.s2"]}


def test_judge_rules_never_return_document_rules_for_a_sentence() -> None:
    rules = judge_rules(_pack(), ReviewScope.SENTENCE, ["controller_identity"], {})
    assert rules
    assert all(rule.scope == "fragment" and rule.kind != "close" for rule in rules)
    assert all(rule.when != "function_absent" for rule in rules)


def test_a_pack_names_before_it_judges() -> None:
    document = parse_text("Kontakt: biuro@firma.pl.")
    pack = _pack()
    decision = MockDecisionClient(
        answers=[
            _named("controller_identity"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
            {"present": False},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "Cele: swiadczenie uslugi."}])

    findings, actions, state = _reviewer(llm, pack, decision).review(document)

    naming = _naming_calls(decision)
    assert len(naming) == 4
    assert [question.kind for question in naming[0].questions.values()] == ["noul", "noul"]
    assert naming[0].questions["controller_identity"] == NoulQuestion(
        yes="Administrator", no="not this function"
    )
    assert all("the whole unused corpus" not in _dump(call.state) for call in naming)
    assert state.covered() == {"controller_identity": ["p1.s1"]}
    gaps = pack.ontology.function_ids() - set(state.covered())
    assert gaps == {"purposes"}

    fragment = next(
        call for call in decision.calls if isinstance(call.state, FragmentDecisionState)
    )
    assert list(fragment.questions) == ["verdict"]
    assert fragment.questions["verdict"].kind == "choice"
    assert fragment.questions["verdict"].options == ("keep", "change", "delete")
    assert "present" not in fragment.questions
    assert fragment.state.tags == ["controller_identity"]
    assert fragment.state.unit is None
    assert "the whole unused corpus" not in _dump(fragment.state)

    closing = next(call for call in decision.calls if isinstance(call.state, DocumentDecisionState))
    assert list(closing.questions) == ["present"]
    assert closing.questions["present"].kind == "noul"
    assert closing.state.candidate == "purposes"
    assert closing.state.candidate not in state.covered()
    assert closing.state.unit is not None
    assert closing.state.unit.id == "unit-controller"
    assert closing.state.unit.force == "binding"
    assert "the whole unused corpus" not in _dump(closing.state)
    assert [finding.title for finding in findings] == ["missing"]
    assert findings[0].description == "purposes"
    assert findings[0].dimension is None
    assert actions == []
    assert llm.calls == []
    assert all(
        "current_review_state" not in _dump(call.state)
        and "external_review_context" not in _dump(call.state)
        and "missing_elements" not in _dump(call.state)
        for call in decision.calls
    )
    assert set(FragmentDecisionState.model_fields) == {"text", "tags", "unit", "comments"}
    assert set(DocumentDecisionState.model_fields) == {"covered", "candidate", "unit", "comments"}


def test_judge_on_a_fragment_never_asks_a_close_rule() -> None:
    document = parse_text("Administratorem jest Firma.")
    decision = MockDecisionClient(
        answers=[
            _named("controller_identity", "purposes"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
        ]
    )
    llm = MockLLMClient()

    _findings, _actions, state = _reviewer(llm, _pack(), decision).review(document)

    assert llm.calls == []
    assert set(state.covered()) == {"controller_identity", "purposes"}
    fragment_calls = [
        call for call in decision.calls if isinstance(call.state, FragmentDecisionState)
    ]
    assert fragment_calls
    for call in fragment_calls:
        assert list(call.questions) == ["verdict"]
        assert call.questions["verdict"].kind == "choice"
        assert "present" not in call.questions
    assert not any(isinstance(call.state, DocumentDecisionState) for call in decision.calls)


def test_document_missing_comes_only_from_covered_gaps() -> None:
    document = parse_text("Administratorem jest Firma.")
    decision = MockDecisionClient(
        answers=[
            _named("controller_identity"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
            {"present": False},
        ]
    )

    findings, _actions, state = _reviewer(MockLLMClient(), _pack(), decision).review(document)

    assert "controller_identity" in state.covered()
    assert "purposes" not in state.covered()
    assert [finding.description for finding in findings if finding.title == "missing"] == [
        "purposes"
    ]
    closing = [call for call in decision.calls if isinstance(call.state, DocumentDecisionState)]
    assert closing[0].state.candidate == "purposes"
    assert [call.state.candidate for call in closing] == ["purposes"]


def test_a_low_confidence_action_goes_to_a_person() -> None:
    document = parse_text("Administratorem jest Firma.")
    decision = MockDecisionClient(
        answers=[
            _named("controller_identity", "purposes"),
            _named(),
            _named(),
            _named(),
            {"verdict": {"value": "change", "confidence": 0.2}},
        ]
    )
    llm = MockLLMClient()

    _findings, actions, _state = _reviewer(llm, _pack(), decision).review(document)

    assert actions[0].requires_human_decision is True
    assert actions[0].replacement_text is None
    assert llm.calls == []


def test_review_requires_pack_and_decision_client() -> None:
    with pytest.raises(TypeError):
        TaktReviewer(profile=_profile(), llm=MockLLMClient())
    with pytest.raises(TypeError):
        TaktReviewer(profile=_profile(), llm=MockLLMClient(), pack=_pack())


def test_review_response_has_no_missing_elements_gap_field() -> None:
    assert "missing_elements" not in ReviewResponse.model_fields
    assert "tags" not in ReviewResponse.model_fields
    from reviewkit import pack, prompts

    assert not hasattr(prompts, "naming_prompt")
    assert not hasattr(prompts, "judge_prompt")
    assert not hasattr(pack, "VerdictResponse")


def test_reviewkit_core_is_sockets_not_a_model_runtime() -> None:
    from typing import Protocol

    from reviewkit.decision import DecisionClient
    from reviewkit.llm import LLMClient

    assert issubclass(DecisionClient, Protocol)
    assert issubclass(LLMClient, Protocol)
    forbidden = (
        "basal",
        "qwen",
        "vllm",
        "jev",
        "zenodo",
        "fp8",
        "nvfp4",
        "http://",
        "https://",
    )
    for path in Path("src/reviewkit").rglob("*.py"):
        text = path.read_text().lower()
        for token in forbidden:
            assert token not in text, f"{path} names {token}"


def test_pack_loads_from_json_and_rejects_the_pre_024_envelope() -> None:
    payload = json.loads(_PACK_FIXTURE.read_text(encoding="utf-8"))
    pack = Pack.model_validate(payload)
    assert pack.ontology.function_ids() == set(_FUNCTIONS)
    assert pack.units["unit-controller"].force == "binding"
    assert [rule.kind for rule in pack.rules] == ["label", "label", "defect", "close"]

    with pytest.raises(ValidationError):
        Pack.model_validate({**payload, "id": "notice", "document_type": "privacy_notice"})
    with pytest.raises(ValidationError):
        Ontology.model_validate(
            {
                "functions": [{"id": "cookies", "label": "Cookies", "attach_to": ["sentence"]}],
                "source_kinds": ["statute"],
            }
        )


def test_pack_models_forbid_extra_fields_and_stay_frozen() -> None:
    pack = _pack()
    with pytest.raises(ValidationError):
        pack.units = {}
    with pytest.raises(ValidationError):
        pack.ontology.functions[0].label = "other"
    with pytest.raises(ValidationError):
        Function.model_validate(
            {"id": "cookies", "label": "Cookies", "attach_to": ["sentence"], "role": "extra"}
        )
    with pytest.raises(ValidationError):
        Ontology(functions=[])
    with pytest.raises(ValidationError):
        Function(id="cookies", label="Cookies", attach_to=["document"])


def test_unified_rule_is_kind_scope_when_not_split_classes() -> None:
    import reviewkit.pack as pack_mod

    for name in ("LabelRule", "DefectRule", "CloseRule"):
        assert not hasattr(pack_mod, name)
    assert list(Rule.model_fields) == [
        "id",
        "kind",
        "function_id",
        "scope",
        "when",
        "source_unit_id",
    ]
    with pytest.raises(ValidationError):
        Rule(
            id="score",
            kind="score",
            function_id="cookies",
            scope="fragment",
            when="always",
        )
    ontology = Ontology(functions=[Function(id="cookies", label="Cookies", attach_to=["sentence"])])
    with pytest.raises(ValidationError):
        Pack(
            ontology=ontology,
            units={},
            rules=[
                Rule(
                    id="label",
                    kind="label",
                    function_id="cookies",
                    scope="document",
                    when="always",
                )
            ],
        )
    with pytest.raises(ValidationError):
        Pack(
            ontology=ontology,
            units={},
            rules=[
                Rule(
                    id="defect",
                    kind="defect",
                    function_id="cookies",
                    scope="document",
                    when="function_present",
                )
            ],
        )


def test_source_unit_force_is_required_data_not_an_enum() -> None:
    assert "status" not in SourceUnit.model_fields
    assert "kind" not in SourceUnit.model_fields
    assert SourceUnit.model_fields["force"].annotation is str
    unit = SourceUnit(id="u", source_id="s", locator="§1", text="repealed text", force="repealed")
    assert unit.force == "repealed"
    with pytest.raises(ValidationError):
        SourceUnit.model_validate({"id": "u", "source_id": "s", "locator": "§1", "text": "t"})
    with pytest.raises(ValidationError):
        SourceUnit.model_validate(
            {
                "id": "u",
                "source_id": "s",
                "locator": "§1",
                "text": "t",
                "force": "binding",
                "kind": "article",
            }
        )


def test_naming_response_and_function_tag_are_tags_only() -> None:
    schema = NamingResponse.model_json_schema()
    assert list(NamingResponse.model_fields) == ["tags"]
    assert set(schema.get("properties", {})) == {"tags"}
    assert schema.get("additionalProperties") is False
    with pytest.raises(ValidationError):
        FunctionTag.model_validate(
            {"node_id": "p1.s1", "function_ids": ["lead"], "findings": [], "actions": []}
        )
    with pytest.raises(ValidationError):
        NamingResponse.model_validate({"tags": [], "verdicts": []})


def test_accepted_tags_drop_unknown_function_ids() -> None:
    pack = _pack()
    response = NamingResponse(
        tags=[
            FunctionTag(
                node_id="p1.s1",
                function_ids=["controller_identity", "not-in-ontology"],
            )
        ]
    )
    trace = check_naming(pack, response)
    by_name = {check.name: check for check in trace.checks}
    assert by_name["function_ids_belong_to_ontology"].passed is False
    assert by_name["naming_has_no_findings_or_actions"].passed is True
    accepted = accepted_tags(pack, response)
    assert accepted == [FunctionTag(node_id="p1.s1", function_ids=["controller_identity"])]


def test_covered_is_true_only_for_named_functions() -> None:
    empty = ReviewState()
    assert empty.covered() == {}
    assert empty.functions_for("p1.s1") == []

    tagged = ReviewState(
        tags=[
            FunctionTag(node_id="p1.s1", function_ids=["lead", "lead"]),
            FunctionTag(node_id="p1.s1", function_ids=["numeric_claim"]),
            FunctionTag(node_id="p1.s2", function_ids=[]),
        ]
    )
    assert tagged.covered() == {"lead": ["p1.s1"], "numeric_claim": ["p1.s1"]}
    assert tagged.functions_for("p1.s1") == ["lead", "lead"]
    assert tagged.functions_for("p1.s2") == []
    assert "absent" not in tagged.covered()


def test_ontology_gaps_come_from_covered_not_missing_elements() -> None:
    pack = _pack()
    state = ReviewState(
        tags=[FunctionTag(node_id="p1.s1", function_ids=["controller_identity"])],
    )
    covered = state.covered()
    assert covered == {"controller_identity": ["p1.s1"]}
    assert "controller_identity" in covered
    assert "purposes" not in covered
    gaps = pack.ontology.function_ids() - set(covered)
    assert gaps == {"purposes"}
    assert "missing_elements" not in ReviewState.model_fields
    assert "missing_elements" not in ReviewResponse.model_fields


def test_judge_rules_match_when_and_scope_not_labels() -> None:
    pack = _pack()
    untagged = judge_rules(pack, ReviewScope.SENTENCE, [], {})
    assert untagged == []

    tagged = judge_rules(pack, ReviewScope.SENTENCE, ["controller_identity"], {})
    assert [rule.id for rule in tagged] == ["defect-controller"]
    assert all(rule.kind != "label" for rule in tagged)

    for scope in (ReviewScope.PARAGRAPH, ReviewScope.SECTION):
        fragment = judge_rules(pack, scope, ["controller_identity"], {})
        assert [rule.id for rule in fragment] == ["defect-controller"]
        assert all(rule.scope == "fragment" and rule.kind != "close" for rule in fragment)

    absent = judge_rules(pack, ReviewScope.DOCUMENT, [], {})
    assert [rule.id for rule in absent] == ["close-purposes"]
    present = judge_rules(pack, ReviewScope.DOCUMENT, [], {"purposes": ["p1.s1"]})
    assert present == []
    assert cited_unit(pack, None) is None
    assert cited_unit(pack, "unit-controller") is pack.units["unit-controller"]
    assert cited_unit(pack, "missing-unit") is None


def test_naming_functions_name_every_scan_scope() -> None:
    pack = _pack()
    for scope in (
        ReviewScope.SENTENCE,
        ReviewScope.PARAGRAPH,
        ReviewScope.SECTION,
        ReviewScope.DOCUMENT,
    ):
        assert [function.id for function in naming_functions(pack, scope)] == list(_FUNCTIONS)


def test_raw_signal_has_no_tags_field() -> None:
    signal = RawSignal(signal_id="s", node_id="p1.s1", detector="judge", deviation=0.0)
    assert "tags" not in RawSignal.__dataclass_fields__
    assert "tags" not in signal.to_json()
    assert "tags" not in signal.evidence
    assert set(signal.to_json()) == {
        "signal_id",
        "node_id",
        "detector",
        "deviation",
        "confidence",
    }


def test_two_scans_name_before_takt_and_keep_tags_off_raw_signals() -> None:
    document = parse_text("Administratorem jest Firma.")
    events: list[str] = []
    takt = _RecordingTakt(events)
    decision = _OrderedDecision(
        events,
        answers=[
            _named("controller_identity"),
            _named(),
            _named(),
            _named(),
            {"verdict": "keep"},
            {"present": False},
        ],
    )
    llm = MockLLMClient(responses=[{"replacement_text": "Cele: swiadczenie uslugi."}])

    _findings, _actions, state = _reviewer(llm, _pack(), decision, takt).review(document)

    naming = _naming_calls(decision)
    assert len(naming) == 4
    assert events[:4] == ["decide", "decide", "decide", "decide"]
    assert "evaluate" not in events[:4]
    assert events.count("evaluate") == 1
    assert state.covered() == {"controller_identity": ["p1.s1"]}
    signals = [signal for call in takt.calls for signal in call.get("raw_signals") or ()]
    assert signals
    for signal in signals:
        assert "tags" not in signal.to_json()
        assert "tags" not in signal.evidence
    assert llm.calls == []


def test_pack_review_calls_llm_only_to_act() -> None:
    document = parse_text("Kontakt: biuro@firma.pl.")
    decision = MockDecisionClient(
        answers=[
            _named("controller_identity", "purposes"),
            _named(),
            _named(),
            _named(),
            {"verdict": {"value": "change", "confidence": 0.95}},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "rewritten lead"}])

    _reviewer(llm, _pack(), decision).review(document)

    assert llm.calls
    assert all(_payload(call)["pass"] == "action" for call in llm.calls)
    assert all(call.schema.__name__ == "ActionText" for call in llm.calls)


def test_review_tree_forwards_pack_and_decision_sockets(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_review(self, document, **kwargs):
        captured["pack"] = self.pack
        captured["decision"] = self.decision
        return [], [], ReviewState()

    monkeypatch.setattr(TaktReviewer, "review", fake_review)
    pack = _pack()
    decision = MockDecisionClient()
    review_tree(
        parse_text("Jedno zdanie."),
        _profile(),
        MockLLMClient(),
        pack=pack,
        decision=decision,
    )
    assert captured["pack"] is pack
    assert captured["decision"] is decision

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from reviewkit.decision import MockDecisionClient, NoulQuestion
from reviewkit.llm import MockLLMClient
from reviewkit.pack import (
    CloseRule,
    DefectRule,
    Function,
    FunctionTag,
    LabelRule,
    NamingResponse,
    Ontology,
    Pack,
    SourceUnit,
)
from reviewkit.parser_text import parse_text
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import TaktDecision


def _profile() -> ReviewProfile:
    return ReviewProfile(
        name="notice",
        language="pl",
        document_type="privacy_notice",
        reviewer_role="reviewer",
    )


def _pack() -> Pack:
    return Pack(
        id="notice",
        document_type="privacy_notice",
        ontology=Ontology(
            functions=[
                Function(id="controller_identity", label="Administrator", attach_to=["sentence"]),
                Function(id="purposes", label="Cele", attach_to=["sentence"]),
            ],
            source_kinds=["statute"],
            unit_kinds=["article"],
        ),
        units={
            "unit-controller": SourceUnit(
                id="unit-controller",
                source_id="source",
                kind="article",
                locator="§1",
                text="identity of the controller",
                status="binding",
            ),
            "unused": SourceUnit(
                id="unused",
                source_id="source",
                kind="article",
                locator="§99",
                text="the whole unused corpus",
                status="dead",
            ),
        },
        rules=[
            LabelRule(id="label-controller", function_id="controller_identity"),
            LabelRule(id="label-purposes", function_id="purposes"),
            DefectRule(id="defect-controller", function_id="controller_identity"),
            CloseRule(
                id="close-purposes",
                function_id="purposes",
                source_unit_id="unit-controller",
            ),
        ],
    )


def _payload(call) -> dict:
    return json.loads(call.messages[1]["content"].split("\n\n", 1)[1])


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value


class _Stable:
    def evaluate(self, **kwargs) -> TaktDecision:
        return TaktDecision(outcome="stable", node_id="n")


def _reviewer(
    llm: MockLLMClient,
    pack: Pack | None,
    decision: MockDecisionClient | None = None,
) -> TaktReviewer:
    return TaktReviewer(
        profile=_profile(),
        llm=llm,
        pack=pack,
        decision=decision,
        takt_client=_Stable(),
    )


def test_pack_rejects_a_rule_that_cites_an_unknown_function() -> None:
    with pytest.raises(ValidationError):
        Pack(
            id="broken",
            document_type="privacy_notice",
            ontology=Ontology(
                functions=[Function(id="cookies", label="Cookies", attach_to=["sentence"])]
            ),
            units={},
            rules=[LabelRule(id="label", function_id="controller_identity")],
        )


def test_pack_rejects_a_rule_that_cites_an_unknown_unit() -> None:
    with pytest.raises(ValidationError):
        Pack(
            id="broken",
            document_type="privacy_notice",
            ontology=Ontology(
                functions=[Function(id="cookies", label="Cookies", attach_to=["sentence"])]
            ),
            units={},
            rules=[
                CloseRule(id="close", function_id="cookies", source_unit_id="missing-unit"),
            ],
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


def test_a_pack_names_before_it_judges() -> None:
    document = parse_text("Kontakt: biuro@firma.pl.")
    pack = _pack()
    decision = MockDecisionClient(
        answers=[
            {"controller_identity": True, "purposes": False},
            {"verdict": "keep"},
            {"present": False},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "Cele: swiadczenie uslugi."}])

    findings, actions, state = _reviewer(llm, pack, decision).review(document)

    naming, fragment, closing = decision.calls
    assert isinstance(naming.state, str)
    assert [question.kind for question in naming.questions.values()] == ["noul", "noul"]
    assert naming.questions["controller_identity"] == NoulQuestion(
        yes="Administrator", no="not this function"
    )
    assert "the whole unused corpus" not in _dump(naming.state)
    assert state.covered() == {"controller_identity": ["p1.s1"]}
    gaps = pack.ontology.function_ids() - set(state.covered())
    assert gaps == {"purposes"}

    assert isinstance(fragment.state, dict)
    assert list(fragment.questions) == ["verdict"]
    assert fragment.questions["verdict"].kind == "choice"
    assert fragment.questions["verdict"].options == ("keep", "change", "delete")
    assert "present" not in fragment.questions
    assert fragment.state["tags"] == ["controller_identity"]
    assert fragment.state["unit"] is None
    assert "the whole unused corpus" not in _dump(fragment.state)

    assert isinstance(closing.state, dict)
    assert list(closing.questions) == ["present"]
    assert closing.questions["present"].kind == "noul"
    assert closing.state["candidate"] == "purposes"
    assert closing.state["candidate"] not in state.covered()
    assert closing.state["unit"]["id"] == "unit-controller"
    assert "the whole unused corpus" not in _dump(closing.state)
    assert [finding.title for finding in findings] == ["missing"]
    assert findings[0].description == "purposes"
    assert actions[0].replacement_text == "Cele: swiadczenie uslugi."
    assert _payload(llm.calls[0])["pass"] == "action"
    assert _payload(llm.calls[0])["verdict"]["kind"] == "missing"
    assert _payload(llm.calls[0])["source"]["id"] == "unit-controller"


def test_judge_on_a_fragment_never_asks_a_close_rule() -> None:
    document = parse_text("Administratorem jest Firma.")
    decision = MockDecisionClient(
        answers=[
            {"controller_identity": True, "purposes": True},
            {"verdict": "keep"},
        ]
    )
    llm = MockLLMClient()

    _findings, _actions, state = _reviewer(llm, _pack(), decision).review(document)

    assert set(state.covered()) == {"controller_identity", "purposes"}
    fragment_calls = [
        call for call in decision.calls if isinstance(call.state, dict) and "tags" in call.state
    ]
    assert fragment_calls
    for call in fragment_calls:
        assert list(call.questions) == ["verdict"]
        assert call.questions["verdict"].kind == "choice"
        assert "present" not in call.questions


def test_document_missing_comes_only_from_covered_gaps() -> None:
    document = parse_text("Administratorem jest Firma.")
    decision = MockDecisionClient(
        answers=[
            {"controller_identity": True, "purposes": False},
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
    closing = [
        call
        for call in decision.calls
        if isinstance(call.state, dict) and "candidate" in call.state
    ]
    assert closing[0].state["candidate"] == "purposes"
    assert [call.state["candidate"] for call in closing] == ["purposes"]


def test_a_low_confidence_action_goes_to_a_person() -> None:
    document = parse_text("Administratorem jest Firma.")
    decision = MockDecisionClient(
        answers=[
            {"controller_identity": True, "purposes": True},
            {"verdict": {"value": "change", "confidence": 0.2}},
        ]
    )
    llm = MockLLMClient()

    _findings, actions, _state = _reviewer(llm, _pack(), decision).review(document)

    assert actions[0].requires_human_decision is True
    assert actions[0].replacement_text is None
    assert llm.calls == []


def test_without_a_pack_the_review_stays_one_pass() -> None:
    document = parse_text("Jedno zdanie.")
    llm = MockLLMClient(responses=[{}, {}, {}])
    decision = MockDecisionClient(answers=[{"should": "not be called"}])

    _reviewer(llm, None, decision).review(document)

    assert llm.calls
    assert decision.calls == []
    assert all('"pass": "naming"' not in call.content for call in llm.calls)
    assert all(call.schema.__name__.endswith("ReviewResponse") for call in llm.calls)


def test_a_pack_review_needs_a_decision_client() -> None:
    with pytest.raises(ValueError, match="DecisionClient"):
        TaktReviewer(profile=_profile(), llm=MockLLMClient(), pack=_pack())


def test_reviewkit_core_does_not_name_model_hosts() -> None:
    for path in Path("src/reviewkit").rglob("*.py"):
        text = path.read_text().lower()
        for token in ("basal", "qwen", "vllm"):
            assert token not in text, f"{path} names {token}"

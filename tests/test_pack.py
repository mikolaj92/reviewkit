import json

import pytest
from pydantic import ValidationError

from reviewkit.llm import MockLLMClient
from reviewkit.pack import (
    CloseRule,
    DefectRule,
    Function,
    LabelRule,
    Ontology,
    Pack,
    SourceUnit,
)
from reviewkit.parser_text import parse_text
from reviewkit.profile import ReviewProfile
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
            "rodo-art-13-1-a": SourceUnit(
                id="rodo-art-13-1-a",
                source_id="rodo",
                kind="article",
                locator="art. 13 ust. 1 lit. a",
                text="tozsamosc administratora",
                status="binding",
            ),
            "unused": SourceUnit(
                id="unused",
                source_id="rodo",
                kind="article",
                locator="art. 99",
                text="caly akt, ktorego nie wolno podac",
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
                source_unit_id="rodo-art-13-1-a",
            ),
        ],
    )


def _payload(call) -> dict:
    return json.loads(call.messages[1]["content"].split("\n\n", 1)[1])


def _reviewer(llm: MockLLMClient, pack: Pack | None) -> TaktReviewer:
    reviewer = TaktReviewer(profile=_profile(), llm=llm, pack=pack, takt_client=_Stable())
    return reviewer


class _Stable:
    def evaluate(self, **kwargs) -> TaktDecision:
        return TaktDecision(outcome="stable", node_id="n")


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


def test_a_pack_names_before_it_judges() -> None:
    document = parse_text("Kontakt: biuro@firma.pl.")
    llm = MockLLMClient(
        responses=[
            {"tags": [{"node_id": "p1.s1", "function_ids": ["controller_identity"]}]},
            {
                "verdicts": [
                    {
                        "node_id": "p1.s1",
                        "kind": "keep",
                        "function_id": "controller_identity",
                    }
                ]
            },
            {
                "verdicts": [
                    {
                        "node_id": "document",
                        "kind": "missing",
                        "function_id": "purposes",
                        "reason": "Brakuje celow",
                    }
                ]
            },
            {"replacement_text": "Cele: swiadczenie uslugi."},
        ]
    )

    findings, actions, state = _reviewer(llm, _pack()).review(document)

    assert [_payload(call)["pass"] for call in llm.calls] == [
        "naming",
        "assessment",
        "assessment",
        "action",
    ]
    naming = _payload(llm.calls[0])
    assert naming["functions"] == [
        {"id": "controller_identity", "label": "Administrator"},
        {"id": "purposes", "label": "Cele"},
    ]
    assert "rules" not in naming
    assert "tozsamosc administratora" not in llm.calls[0].content
    assert state.covered() == {"controller_identity": ["p1.s1"]}

    fragment = _payload(llm.calls[1])
    assert fragment["scope"] == "fragment"
    assert [rule["kind"] for rule in fragment["rules"]] == ["defect"]
    assert fragment["sources"] == []

    document_pass = _payload(llm.calls[2])
    assert document_pass["scope"] == "document"
    assert [rule["kind"] for rule in document_pass["rules"]] == ["close"]
    assert [unit["id"] for unit in document_pass["sources"]] == ["rodo-art-13-1-a"]
    assert "caly akt" not in llm.calls[2].content
    assert findings[0].title == "missing"
    assert findings[0].description == "Brakuje celow"
    assert actions[0].replacement_text == "Cele: swiadczenie uslugi."
    assert _payload(llm.calls[3])["verdict"]["kind"] == "missing"
    assert _payload(llm.calls[3])["source"]["id"] == "rodo-art-13-1-a"


def test_a_low_confidence_action_goes_to_a_person() -> None:
    document = parse_text("Administratorem jest Firma.")
    llm = MockLLMClient(
        responses=[
            {"tags": [{"node_id": "p1.s1", "function_ids": ["controller_identity"]}]},
            {
                "verdicts": [
                    {
                        "node_id": "p1.s1",
                        "kind": "change",
                        "function_id": "controller_identity",
                        "confidence": 0.2,
                    }
                ]
            },
            {
                "verdicts": [
                    {"node_id": "document", "kind": "keep", "function_id": "purposes"}
                ]
            },
        ]
    )

    _findings, actions, _state = _reviewer(llm, _pack()).review(document)

    assert actions[0].requires_human_decision is True
    assert actions[0].replacement_text is None
    assert all(_payload(call)["pass"] != "action" for call in llm.calls)


def test_without_a_pack_the_review_stays_one_pass() -> None:
    document = parse_text("Jedno zdanie.")
    llm = MockLLMClient(responses=[{}, {}, {}])

    _reviewer(llm, None).review(document)

    assert llm.calls
    assert all('"pass": "naming"' not in call.content for call in llm.calls)
    assert all(call.schema.__name__.endswith("ReviewResponse") for call in llm.calls)

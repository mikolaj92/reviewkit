"""Lock the 0.24 host import surface on the package root."""

from __future__ import annotations

import inspect
from typing import Protocol

import reviewkit
from reviewkit import (
    ActionText,
    DecisionAnswer,
    DecisionClient,
    DocumentDecisionState,
    FragmentDecisionState,
    FunctionTag,
    LLMClient,
    MockDecisionClient,
    MockLLMClient,
    NamingResponse,
    NoulQuestion,
    VerdictKind,
    review_document,
    review_source,
    review_tree,
)

_HOST_PACK_SURFACE = (
    "ActionText",
    "ChoiceQuestion",
    "DecisionAnswer",
    "DecisionCall",
    "DecisionClient",
    "DocumentDecisionState",
    "FragmentDecisionState",
    "Function",
    "FunctionTag",
    "MockDecisionClient",
    "NamingResponse",
    "NoulQuestion",
    "Ontology",
    "Pack",
    "PassTrace",
    "ProcessCheck",
    "Question",
    "ReviewState",
    "Rule",
    "SourceUnit",
    "TaktReviewer",
    "Verdict",
    "VerdictKind",
)


def test_host_pack_and_plugin_types_are_exported_from_package_root() -> None:
    for name in _HOST_PACK_SURFACE:
        assert name in reviewkit.__all__, name
        assert getattr(reviewkit, name) is not None


def test_host_entry_points_accept_pack_and_decision() -> None:
    for func in (review_tree, review_source, review_document):
        params = inspect.signature(func).parameters
        assert "pack" in params
        assert "decision" in params
        assert params["pack"].default is None
        assert params["decision"].default is None


def test_plugin_sockets_are_protocols_with_typed_methods() -> None:
    assert issubclass(DecisionClient, Protocol)
    assert issubclass(LLMClient, Protocol)
    decide = inspect.signature(DecisionClient.decide)
    complete = inspect.signature(LLMClient.complete_json)
    assert list(decide.parameters) == ["self", "state", "questions"]
    assert list(complete.parameters)[:3] == ["self", "messages", "schema"]
    assert "options" in complete.parameters


def test_decision_state_typed_dicts_match_scan_payloads() -> None:
    fragment: FragmentDecisionState = {"text": "x", "tags": ["lead"], "unit": None}
    document: DocumentDecisionState = {"covered": [], "candidate": "lead", "unit": None}
    assert set(fragment) == {"text", "tags", "unit"}
    assert set(document) == {"covered", "candidate", "unit"}
    assert FunctionTag(node_id="n", function_ids=["lead"]).function_ids == ["lead"]
    assert list(NamingResponse.model_fields) == ["tags"]
    assert VerdictKind.CHANGE.value == "change"
    assert ActionText(replacement_text=None).replacement_text is None


def test_mock_clients_satisfy_host_sockets() -> None:
    decision = MockDecisionClient()
    llm = MockLLMClient()
    assert isinstance(decision, DecisionClient)
    answers = decision.decide("fragment", {"lead": NoulQuestion(yes="Lead")})
    assert answers["lead"] == DecisionAnswer(value=False)
    assert callable(llm.complete_json)

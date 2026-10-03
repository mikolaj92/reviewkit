"""Lock the 0.24 host import surface on the package root."""

from __future__ import annotations

import inspect
from typing import Protocol

import reviewkit
from reviewkit import (
    ActionText,
    DecisionAnswer,
    DecisionClient,
    DecisionState,
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
    "DecisionState",
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


def test_host_entry_points_require_pack_and_decision() -> None:
    for func in (review_tree, review_source, review_document):
        params = inspect.signature(func).parameters
        assert "pack" in params
        assert "decision" in params
        assert params["pack"].default is inspect.Parameter.empty
        assert params["decision"].default is inspect.Parameter.empty
        assert "Pack" in str(params["pack"].annotation)
        assert "DecisionClient" in str(params["decision"].annotation)
        assert params["passes"].default == 1
        assert params["prior"].default is None
        assert params["level"].default is None
    review_params = inspect.signature(reviewkit.TaktReviewer.review).parameters
    assert review_params["passes"].default == 1
    assert review_params["prior"].default is None
    assert review_params["level"].default is None


def test_plugin_sockets_are_protocols_with_typed_methods() -> None:
    assert issubclass(DecisionClient, Protocol)
    assert issubclass(LLMClient, Protocol)
    decide = inspect.signature(DecisionClient.decide)
    complete = inspect.signature(LLMClient.complete_json)
    assert list(decide.parameters) == ["self", "state", "questions"]
    assert list(complete.parameters)[:3] == ["self", "messages", "schema"]
    assert "options" in complete.parameters


def test_decision_states_are_typed_models_not_dicts() -> None:
    fragment = FragmentDecisionState(text="x", tags=["lead"], unit=None)
    document = DocumentDecisionState(covered=[], candidate="lead", unit=None)
    assert set(FragmentDecisionState.model_fields) == {"text", "tags", "unit", "comments"}
    assert set(DocumentDecisionState.model_fields) == {"covered", "candidate", "unit", "comments"}
    assert fragment.tags == ["lead"]
    assert fragment.comments == []
    assert document.candidate == "lead"
    assert document.comments == []
    assert isinstance(fragment, reviewkit.FragmentDecisionState)
    state: DecisionState = fragment
    assert state.text == "x"
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


def test_hosts_construct_pack_from_python_objects() -> None:
    pack = reviewkit.Pack(
        ontology=reviewkit.Ontology(
            functions=[
                reviewkit.Function(id="lead", label="Lead", attach_to=["sentence"]),
            ]
        ),
        units={},
        rules=[],
    )
    assert pack.ontology.function_ids() == {"lead"}
    from_json = reviewkit.Pack.model_validate(pack.model_dump())
    assert from_json == pack


def test_legacy_detect_apis_are_not_on_the_package_root() -> None:
    for name in (
        "BaseLLMDetector",
        "RawSignal",
        "TaktClient",
        "DocNode",
        "ReviewDocumentPlant",
        "detect",
        "judge",
    ):
        assert name not in reviewkit.__all__, name
        assert not hasattr(reviewkit, name)

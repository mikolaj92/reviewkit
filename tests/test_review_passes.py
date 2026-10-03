"""Recursive per-fragment review: courses, settle/repeat/further, prior."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from reviewkit.courses import CourseMove
from reviewkit.decision import (
    DecisionAnswer,
    DecisionCall,
    DecisionState,
    FragmentDecisionState,
    Question,
)
from reviewkit.llm import MockLLMClient
from reviewkit.models import ReviewResult, ReviewScope
from reviewkit.pack import Function, Ontology, Pack, Rule
from reviewkit.parser_text import parse_text
from reviewkit.plant import ReviewDocumentPlant
from reviewkit.profile import ReviewProfile
from reviewkit.review import review_tree
from reviewkit.state import ReviewState
from reviewkit.takt_reviewer import TaktReviewer
from reviewkit.takt_types import TaktDecision

_SENTENCE_NOTE = "sentence-note"


def _profile() -> ReviewProfile:
    return ReviewProfile(
        name="notice",
        language="en",
        document_type="notice",
        reviewer_role="reviewer",
    )


def _pack() -> Pack:
    return Pack(
        ontology=Ontology(functions=[Function(id="lead", label="Lead", attach_to=["sentence"])]),
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


class _StableTakt:
    def evaluate(self, **kwargs) -> TaktDecision:
        node_id = kwargs["plant_nodes"][0].id
        return TaktDecision(outcome="stable", node_id=node_id)  # type: ignore[arg-type]


class _PassDecision:
    """Own-text comments on a first visit; later visits with comments keep."""

    def __init__(self) -> None:
        self.calls: list[DecisionCall] = []

    def decide(
        self, state: DecisionState, questions: Mapping[str, Question]
    ) -> dict[str, DecisionAnswer]:
        recorded = {key: question for key, question in questions.items()}
        self.calls.append(DecisionCall(state=state, questions=recorded))
        if "verdict" in questions:
            assert isinstance(state, FragmentDecisionState)
            if state.comments:
                return {"verdict": DecisionAnswer(value="keep")}
            if "lead" in state.tags:
                return {
                    "verdict": DecisionAnswer(
                        value="change",
                        reason=_SENTENCE_NOTE,
                        confidence=0.5,
                    )
                }
            return {"verdict": DecisionAnswer(value="keep")}
        if "present" in questions:
            return {"present": DecisionAnswer(value=True)}
        return {key: DecisionAnswer(value=True) for key in recorded}


class _KeepDecision:
    """Never produce comments or labels. Empty delta should settle."""

    def __init__(self) -> None:
        self.calls: list[DecisionCall] = []

    def decide(
        self, state: DecisionState, questions: Mapping[str, Question]
    ) -> dict[str, DecisionAnswer]:
        recorded = {key: question for key, question in questions.items()}
        self.calls.append(DecisionCall(state=state, questions=recorded))
        if "verdict" in questions:
            return {"verdict": DecisionAnswer(value="keep")}
        if "present" in questions:
            return {"present": DecisionAnswer(value=True)}
        return {key: DecisionAnswer(value=False) for key in recorded}


def _reviewer(decision: object) -> TaktReviewer:
    return TaktReviewer(
        profile=_profile(),
        llm=MockLLMClient(),
        pack=_pack(),
        decision=decision,  # type: ignore[arg-type]
        takt_client=_StableTakt(),  # type: ignore[arg-type]
    )


def test_call_with_nothing_extra_returns_review_result_and_appends_courses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reviewkit.takt_reviewer.TaktClient", _StableTakt)
    document = parse_text("A lead sentence.")
    result = review_tree(
        document, _profile(), MockLLMClient(), pack=_pack(), decision=_KeepDecision()
    )
    assert isinstance(result, ReviewResult)
    assert result.state is not None
    assert result.state.courses
    assert all(
        course.move in {CourseMove.SETTLE, CourseMove.REPEAT, CourseMove.FURTHER}
        for course in result.state.courses
    )
    assert any(course.grain is ReviewScope.DOCUMENT for course in result.state.courses)
    assert "state" not in result.to_report_dict()
    assert hasattr(ReviewState(), "courses")


def test_empty_delta_settles_and_is_not_judged_again() -> None:
    document = parse_text("A lead sentence.")
    decision = _KeepDecision()
    _findings, _actions, state = _reviewer(decision).review(document)
    sentence_rows = [
        course
        for course in state.courses
        if course.node_id == "p1.s1" and course.grain is ReviewScope.SENTENCE
    ]
    assert sentence_rows
    assert sentence_rows[-1].move is CourseMove.SETTLE
    assert len(sentence_rows) == 1


def test_fragment_named_by_new_document_action_is_judged_again() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision()
    _findings, _actions, state = _reviewer(decision).review(document)
    sentence_verdicts = [
        call
        for call in decision.calls
        if "verdict" in call.questions and isinstance(call.state, FragmentDecisionState)
    ]
    assert len(sentence_verdicts) >= 2
    document_rows = [course for course in state.courses if course.grain is ReviewScope.DOCUMENT]
    assert document_rows
    assert document_rows[-1].move in {CourseMove.SETTLE, CourseMove.REPEAT, CourseMove.FURTHER}
    sentence_rows = [
        course
        for course in state.courses
        if course.node_id == "p1.s1" and course.grain is ReviewScope.SENTENCE
    ]
    assert len(sentence_rows) >= 2


def test_passes_and_level_are_type_errors() -> None:
    document = parse_text("A lead sentence.")
    reviewer = _reviewer(_KeepDecision())
    with pytest.raises(TypeError):
        reviewer.review(document, passes=2)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        reviewer.review(document, level="sentence")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        review_tree(
            document,
            _profile(),
            MockLLMClient(),
            pack=_pack(),
            decision=_KeepDecision(),  # type: ignore[arg-type]
            passes=2,
        )
    with pytest.raises(TypeError):
        review_tree(
            document,
            _profile(),
            MockLLMClient(),
            pack=_pack(),
            decision=_KeepDecision(),  # type: ignore[arg-type]
            level=ReviewScope.SENTENCE,
        )


def test_prior_reenters_with_earlier_discoveries() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision()
    first = _reviewer(decision).review(document)
    second = _reviewer(decision).review(document, prior=first)
    assert second[2].courses
    assert any(action.reason and _SENTENCE_NOTE in action.reason for action in second[1])
    assert any("lead" in (tag.function_ids or []) for tag in second[2].tags)


def test_contained_node_ids_include_smaller_units() -> None:
    document = parse_text("A lead sentence.")
    plant = ReviewDocumentPlant(document)
    assert plant.root.descendant_ids() == ["s1", "p1", "p1.s1"]

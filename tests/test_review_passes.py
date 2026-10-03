"""Caller-chosen review passes feed earlier comments and labels forward."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from reviewkit.decision import (
    DecisionAnswer,
    DecisionCall,
    DecisionState,
    FragmentDecisionState,
    Question,
)
from reviewkit.llm import MockLLMClient
from reviewkit.pack import Function, Ontology, Pack, Rule
from reviewkit.parser_text import parse_text
from reviewkit.plant import ReviewDocumentPlant
from reviewkit.profile import ReviewProfile
from reviewkit.review import review_tree
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
    """Scriptable plugin: pass 1 comments from own text; later passes echo feedback."""

    def __init__(self, *, name_only_sentence: bool = False) -> None:
        self.name_only_sentence = name_only_sentence
        self.calls: list[DecisionCall] = []
        self._names = 0

    def decide(
        self, state: DecisionState, questions: Mapping[str, Question]
    ) -> dict[str, DecisionAnswer]:
        recorded = {key: question for key, question in questions.items()}
        self.calls.append(DecisionCall(state=state, questions=recorded))
        if "verdict" in questions:
            assert isinstance(state, FragmentDecisionState)
            if state.comments:
                return {
                    "verdict": DecisionAnswer(
                        value="change",
                        reason="later:" + "|".join(state.comments),
                        confidence=0.5,
                    )
                }
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
        yes = (not self.name_only_sentence) or self._names == 0
        self._names += 1
        return {key: DecisionAnswer(value=yes) for key in recorded}


def _reviewer(decision: _PassDecision) -> TaktReviewer:
    return TaktReviewer(
        profile=_profile(),
        llm=MockLLMClient(),
        pack=_pack(),
        decision=decision,  # type: ignore[arg-type]
        takt_client=_StableTakt(),  # type: ignore[arg-type]
    )


def _fragment_states(decision: _PassDecision) -> list[FragmentDecisionState]:
    return [call.state for call in decision.calls if isinstance(call.state, FragmentDecisionState)]


def _result_snapshot(findings: list, actions: list, state) -> tuple[tuple, tuple, tuple]:
    return (
        tuple((finding.node_id, finding.title, finding.description) for finding in findings),
        tuple((action.node_id, action.action_type.value, action.reason) for action in actions),
        tuple((tag.node_id, tuple(tag.function_ids)) for tag in state.tags),
    )


def test_default_pass_ignores_contained_comment_text() -> None:
    """Post-order still does not feed sentence comments into a larger unit on pass 1."""
    document = parse_text("A lead sentence.")
    decision = _PassDecision()
    findings, actions, state = _reviewer(decision).review(document)

    fragments = _fragment_states(decision)
    assert fragments
    assert [fragment.comments for fragment in fragments] == [[] for _ in fragments]
    assert len(fragments) >= 2
    assert any(action.reason == _SENTENCE_NOTE for action in actions)
    assert "lead" in state.covered()
    assert [finding.title for finding in findings]


def test_passes_one_matches_omitted_passes() -> None:
    document = parse_text("A lead sentence.")
    default_decision = _PassDecision()
    once_decision = _PassDecision()
    default = _reviewer(default_decision).review(document)
    once = _reviewer(once_decision).review(document, passes=1)

    assert _result_snapshot(*default) == _result_snapshot(*once)
    assert len(default_decision.calls) == len(once_decision.calls)
    assert all(fragment.comments == [] for fragment in _fragment_states(default_decision))


def test_two_passes_feed_contained_comments_and_labels() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_sentence=True)
    findings, actions, state = _reviewer(decision).review(document, passes=2)

    fragments = _fragment_states(decision)
    first, later = fragments[0], fragments[1:]
    assert first.comments == []
    assert first.tags == ["lead"]
    assert later
    assert any(fragment.comments == [_SENTENCE_NOTE] for fragment in later)
    assert any("lead" in fragment.tags and fragment.comments for fragment in later)
    assert state.covered() == {"lead": ["p1.s1"]}
    assert any(action.reason == _SENTENCE_NOTE for action in actions)
    assert any(action.reason == f"later:{_SENTENCE_NOTE}" for action in actions)
    assert any(finding.title == "change" for finding in findings)


def test_three_passes_carry_earlier_comments_and_labels_forward() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_sentence=True)
    findings, actions, state = _reviewer(decision).review(document, passes=3)

    later = [fragment for fragment in _fragment_states(decision) if fragment.comments]
    assert any(_SENTENCE_NOTE in fragment.comments for fragment in later)
    assert any(
        f"later:{_SENTENCE_NOTE}" in fragment.comments and _SENTENCE_NOTE in fragment.comments
        for fragment in later
    )
    assert all("lead" in fragment.tags for fragment in later)
    reasons = [action.reason for action in actions]
    assert _SENTENCE_NOTE in reasons
    assert f"later:{_SENTENCE_NOTE}" in reasons
    assert any(
        reason is not None and reason.startswith("later:") and "|" in reason for reason in reasons
    )
    assert state.covered() == {"lead": ["p1.s1"]}
    assert any(tag.function_ids == ["lead"] and tag.node_id == "p1.s1" for tag in state.tags)
    assert findings


def test_review_tree_forwards_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reviewkit.takt_reviewer.TaktClient", _StableTakt)
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_sentence=True)
    result = review_tree(
        document,
        _profile(),
        MockLLMClient(),
        pack=_pack(),
        decision=decision,  # type: ignore[arg-type]
        passes=2,
    )
    assert any(action.reason == _SENTENCE_NOTE for action in result.actions)
    assert any(action.reason == f"later:{_SENTENCE_NOTE}" for action in result.actions)
    assert any(fragment.comments == [_SENTENCE_NOTE] for fragment in _fragment_states(decision))


def test_passes_must_be_at_least_one() -> None:
    document = parse_text("A lead sentence.")
    with pytest.raises(ValueError, match="passes must be >= 1"):
        _reviewer(_PassDecision()).review(document, passes=0)


def test_contained_node_ids_include_smaller_units() -> None:
    document = parse_text("A lead sentence.")
    plant = ReviewDocumentPlant(document)
    assert plant.root.descendant_ids() == ["s1", "p1", "p1.s1"]

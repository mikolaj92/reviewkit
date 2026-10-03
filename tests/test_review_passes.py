"""A later review call continues from comments and labels already produced."""

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
from reviewkit.models import ReviewScope
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
    """Own-text comments on a first call; a later call echoes comments it was given."""

    def __init__(self, *, name_only_first: bool = False) -> None:
        self.name_only_first = name_only_first
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
        yes = (not self.name_only_first) or self._names == 0
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


def _naming_calls(decision: _PassDecision) -> list[DecisionCall]:
    return [call for call in decision.calls if isinstance(call.state, str)]


def _result_snapshot(findings: list, actions: list, state) -> tuple[tuple, tuple, tuple]:
    return (
        tuple((finding.node_id, finding.title, finding.description) for finding in findings),
        tuple((action.node_id, action.action_type.value, action.reason) for action in actions),
        tuple((tag.node_id, tuple(tag.function_ids)) for tag in state.tags),
    )


def test_call_with_no_prior_and_no_level_matches_today() -> None:
    document = parse_text("A lead sentence.")
    omitted = _PassDecision()
    explicit = _PassDecision()
    default = _reviewer(omitted).review(document)
    none = _reviewer(explicit).review(document, prior=None, level=None)

    assert _result_snapshot(*default) == _result_snapshot(*none)
    assert len(omitted.calls) == len(explicit.calls)
    assert all(fragment.comments == [] for fragment in _fragment_states(omitted))
    assert all(fragment.comments == [] for fragment in _fragment_states(explicit))
    assert len(_naming_calls(omitted)) > 1
    assert len(_fragment_states(omitted)) > 1


def test_default_walk_ignores_contained_comment_text() -> None:
    """Today's full walk still does not feed sentence comments into a larger unit."""
    document = parse_text("A lead sentence.")
    decision = _PassDecision()
    findings, actions, state = _reviewer(decision).review(document)

    fragments = _fragment_states(decision)
    assert fragments
    assert [fragment.comments for fragment in fragments] == [[] for _ in fragments]
    assert len(fragments) >= 2
    assert any(action.reason and _SENTENCE_NOTE in action.reason for action in actions)
    assert "lead" in state.covered()
    assert findings


def test_level_runs_only_units_of_that_size() -> None:
    document = parse_text("A lead sentence. Second sentence.")
    decision = _PassDecision()
    _findings, actions, state = _reviewer(decision).review(document, level=ReviewScope.SENTENCE)

    assert len(_naming_calls(decision)) == 2
    assert len(_fragment_states(decision)) == 2
    assert {action.node_id for action in actions} <= {"p1.s1", "p1.s2"}
    assert all(fragment.comments == [] for fragment in _fragment_states(decision))
    assert state.covered() == {"lead": ["p1.s1", "p1.s2"]}


def test_second_sentence_call_sees_comments_and_labels_from_first() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_first=True)
    first = _reviewer(decision).review(document, level="sentence")
    after_first = len(_fragment_states(decision))
    assert after_first == 1
    assert all(fragment.comments == [] for fragment in _fragment_states(decision))

    second = _reviewer(decision).review(document, level=ReviewScope.SENTENCE, prior=first)
    later = _fragment_states(decision)[after_first:]
    assert later
    assert any(_SENTENCE_NOTE in comment for fragment in later for comment in fragment.comments)
    assert all("lead" in fragment.tags for fragment in later)
    findings, actions, state = second
    assert state.covered() == {"lead": ["p1.s1"]}
    assert any(action.reason and _SENTENCE_NOTE in action.reason for action in actions)
    assert any(action.reason and action.reason.startswith("later:") for action in actions)
    assert any(finding.title == "change" for finding in findings)
    assert len(_naming_calls(decision)) == 2


def test_third_sentence_call_sees_both_earlier_results() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_first=True)
    first = _reviewer(decision).review(document, level=ReviewScope.SENTENCE)
    second = _reviewer(decision).review(document, level=ReviewScope.SENTENCE, prior=first)
    after_second = len(_fragment_states(decision))
    third = _reviewer(decision).review(document, level=ReviewScope.SENTENCE, prior=second)

    later = _fragment_states(decision)[after_second:]
    assert any(_SENTENCE_NOTE in comment for fragment in later for comment in fragment.comments)
    assert any(
        any("later:" in comment for comment in fragment.comments)
        and any(_SENTENCE_NOTE in comment for comment in fragment.comments)
        for fragment in later
    )
    assert all("lead" in fragment.tags for fragment in later)
    findings, actions, state = third
    reasons = [action.reason or "" for action in actions]
    assert any(_SENTENCE_NOTE in reason for reason in reasons)
    assert any(reason.startswith("later:") for reason in reasons)
    assert any(first_action.reason in reasons for first_action in first[1] if first_action.reason)
    assert any(
        second_action.reason in reasons for second_action in second[1] if second_action.reason
    )
    assert state.covered() == {"lead": ["p1.s1"]}
    assert any(tag.function_ids == ["lead"] and tag.node_id == "p1.s1" for tag in state.tags)
    assert findings
    assert len(_fragment_states(decision)) == after_second + 1


def test_paragraph_call_after_sentences_sees_earlier_discoveries() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_first=True)
    first = _reviewer(decision).review(document, level=ReviewScope.SENTENCE)
    second = _reviewer(decision).review(document, level=ReviewScope.SENTENCE, prior=first)
    after_sentences = len(_fragment_states(decision))
    paragraph = _reviewer(decision).review(document, level=ReviewScope.PARAGRAPH, prior=second)

    later = _fragment_states(decision)[after_sentences:]
    assert later
    assert all("lead" in fragment.tags for fragment in later)
    assert any(_SENTENCE_NOTE in comment for fragment in later for comment in fragment.comments)
    assert any("later:" in comment for fragment in later for comment in fragment.comments)
    findings, actions, state = paragraph
    assert any(action.node_id == "p1" for action in actions)
    assert any(action.node_id == "p1.s1" for action in actions)
    assert any(action.reason and action.reason.startswith("later:") for action in actions)
    assert state.covered()["lead"] == ["p1.s1"]
    assert findings
    assert len(_naming_calls(decision)) == after_sentences + 1


def test_second_paragraph_call_sees_sentence_and_paragraph_discoveries() -> None:
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_first=True)
    sentences = _reviewer(decision).review(document, level=ReviewScope.SENTENCE)
    first_paragraph = _reviewer(decision).review(
        document, level=ReviewScope.PARAGRAPH, prior=sentences
    )
    after_first_paragraph = len(_fragment_states(decision))
    second_paragraph = _reviewer(decision).review(
        document, level=ReviewScope.PARAGRAPH, prior=first_paragraph
    )

    later = _fragment_states(decision)[after_first_paragraph:]
    assert later
    assert any(_SENTENCE_NOTE in comment for fragment in later for comment in fragment.comments)
    assert any("later:" in comment for fragment in later for comment in fragment.comments)
    findings, actions, state = second_paragraph
    reasons = [action.reason or "" for action in actions]
    assert any(
        action.node_id == "p1" and (action.reason or "").startswith("later:") for action in actions
    )
    assert any(_SENTENCE_NOTE in reason for reason in reasons)
    assert any(
        first_action.reason in reasons for first_action in first_paragraph[1] if first_action.reason
    )
    assert state.covered()["lead"] == ["p1.s1"]
    assert findings


def test_review_tree_picks_a_level_and_reenters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reviewkit.takt_reviewer.TaktClient", _StableTakt)
    document = parse_text("A lead sentence.")
    decision = _PassDecision(name_only_first=True)
    first = review_tree(
        document,
        _profile(),
        MockLLMClient(),
        pack=_pack(),
        decision=decision,  # type: ignore[arg-type]
        level=ReviewScope.SENTENCE,
    )
    second = review_tree(
        document,
        _profile(),
        MockLLMClient(),
        pack=_pack(),
        decision=decision,  # type: ignore[arg-type]
        level=ReviewScope.SENTENCE,
        prior=first,
    )
    assert any(action.reason and _SENTENCE_NOTE in action.reason for action in second.actions)
    assert any(action.reason and action.reason.startswith("later:") for action in second.actions)
    assert second.state is not None
    assert second.state.covered() == {"lead": ["p1.s1"]}
    assert any(
        _SENTENCE_NOTE in comment
        for fragment in _fragment_states(decision)
        for comment in fragment.comments
    )


def test_passes_convenience_repeats_the_same_level() -> None:
    document = parse_text("A lead sentence.")
    looped = _PassDecision(name_only_first=True)
    separate = _PassDecision(name_only_first=True)
    once = _reviewer(looped).review(document, level=ReviewScope.SENTENCE, passes=2)
    first = _reviewer(separate).review(document, level=ReviewScope.SENTENCE)
    twice = _reviewer(separate).review(document, level=ReviewScope.SENTENCE, prior=first)
    assert _result_snapshot(*once) == _result_snapshot(*twice)


def test_passes_must_be_at_least_one() -> None:
    document = parse_text("A lead sentence.")
    with pytest.raises(ValueError, match="passes must be >= 1"):
        _reviewer(_PassDecision()).review(document, passes=0)


def test_level_must_be_in_the_pipeline() -> None:
    document = parse_text("A lead sentence.")
    reviewer = TaktReviewer(
        profile=ReviewProfile(
            name="notice",
            language="en",
            document_type="notice",
            reviewer_role="reviewer",
            review_pipeline=[ReviewScope.SENTENCE],
        ),
        llm=MockLLMClient(),
        pack=_pack(),
        decision=_PassDecision(),  # type: ignore[arg-type]
        takt_client=_StableTakt(),  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="level 'paragraph' is not in review_pipeline"):
        reviewer.review(document, level=ReviewScope.PARAGRAPH)


def test_contained_node_ids_include_smaller_units() -> None:
    document = parse_text("A lead sentence.")
    plant = ReviewDocumentPlant(document)
    assert plant.root.descendant_ids() == ["s1", "p1", "p1.s1"]

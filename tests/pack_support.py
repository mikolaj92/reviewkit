"""Shared Pack + DecisionClient fixtures for Pack-only review tests."""

from __future__ import annotations

from collections.abc import Mapping

from reviewkit.decision import (
    ChoiceQuestion,
    DecisionAnswer,
    DecisionCall,
    DecisionState,
    MockDecisionClient,
    NoulQuestion,
    Question,
    coerce_answer,
)
from reviewkit.pack import Function, Ontology, Pack, Rule


def silent_pack() -> Pack:
    """Ontology only. No defect or close rules, so judge emits nothing."""
    return Pack(
        ontology=Ontology(
            functions=[
                Function(
                    id="claim",
                    label="Claim",
                    attach_to=["sentence", "paragraph", "section"],
                )
            ]
        ),
        units={},
        rules=[],
    )


def silent_decision() -> MockDecisionClient:
    return MockDecisionClient()


def defect_pack() -> Pack:
    """One fragment defect so judge can emit signals when the function is named."""
    return Pack(
        ontology=Ontology(
            functions=[
                Function(
                    id="claim",
                    label="Claim",
                    attach_to=["sentence", "paragraph", "section"],
                )
            ]
        ),
        units={},
        rules=[
            Rule(
                id="defect-claim",
                kind="defect",
                function_id="claim",
                scope="fragment",
                when="function_present",
            )
        ],
    )


class ChangeDecisionClient:
    """Names every function and judges change so takt receives signals."""

    def __init__(self) -> None:
        self.calls: list[DecisionCall] = []

    def decide(
        self,
        state: DecisionState,
        questions: Mapping[str, Question],
    ) -> dict[str, DecisionAnswer]:
        recorded = {key: question for key, question in questions.items()}
        self.calls.append(DecisionCall(state=state, questions=recorded))
        result: dict[str, DecisionAnswer] = {}
        for key, question in recorded.items():
            if key == "verdict" and isinstance(question, ChoiceQuestion):
                result[key] = coerce_answer("change")
            elif isinstance(question, NoulQuestion):
                result[key] = DecisionAnswer(value=True)
            else:
                result[key] = DecisionAnswer(value=True)
        return result


def change_decision() -> ChangeDecisionClient:
    return ChangeDecisionClient()

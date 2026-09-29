"""Provider-blind decision protocol for Pack naming and judging.

The host injects the plugin at the call site. This module is a socket, not a
model runtime: no server client, weight name, or URL lives here. A Pack review
calls :meth:`DecisionClient.decide` to name and judge. Replacement text goes
through :class:`~reviewkit.llm.LLMClient`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from reviewkit.pack import SourceUnit

_STRICT = ConfigDict(extra="forbid", frozen=True)


class NoulQuestion(BaseModel):
    """Yes/no question. Multi-label naming uses one of these per function id."""

    model_config = _STRICT

    kind: Literal["noul"] = "noul"
    yes: str
    no: str = "not this"


class ChoiceQuestion(BaseModel):
    """Enumerated question. Fragment judging uses keep/change/delete."""

    model_config = _STRICT

    kind: Literal["choice"] = "choice"
    options: tuple[str, ...]


Question = NoulQuestion | ChoiceQuestion


class DecisionAnswer(BaseModel):
    model_config = _STRICT

    value: bool | str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""


class FragmentDecisionState(BaseModel):
    """Scan-2 fragment payload: the node text, its tags, and the cited unit."""

    model_config = _STRICT

    text: str
    tags: list[str]
    unit: SourceUnit | None = None


class DocumentDecisionState(BaseModel):
    """Scan-2 document payload: coverage for one function and the cited unit."""

    model_config = _STRICT

    covered: list[str]
    candidate: str
    unit: SourceUnit | None = None


type DecisionState = str | FragmentDecisionState | DocumentDecisionState
type RawDecisionAnswer = DecisionAnswer | bool | str | Mapping[str, Any]
type DecisionAnswers = Mapping[str, RawDecisionAnswer]


@runtime_checkable
class LabeledFunction(Protocol):
    id: str
    label: str


@runtime_checkable
class DecisionClient(Protocol):
    """Decision dependency supplied by the ReviewKit host.

    Naming passes the fragment text (``str``). Judging passes typed
    :class:`FragmentDecisionState` or :class:`DocumentDecisionState` objects,
    including the cited :class:`~reviewkit.pack.SourceUnit` when a rule has one.
    """

    def decide(
        self,
        state: DecisionState,
        questions: Mapping[str, Question],
    ) -> DecisionAnswers: ...


@dataclass(frozen=True)
class DecisionCall:
    state: DecisionState
    questions: dict[str, Question]


class MockDecisionClient:
    """Scriptable fake for tests. No network, no weights."""

    def __init__(
        self,
        answers: Sequence[DecisionAnswers] | None = None,
    ) -> None:
        self._answers = list(answers or [])
        self.calls: list[DecisionCall] = []

    def decide(
        self,
        state: DecisionState,
        questions: Mapping[str, Question],
    ) -> dict[str, DecisionAnswer]:
        recorded = {key: question for key, question in questions.items()}
        self.calls.append(DecisionCall(state=state, questions=recorded))
        scripted = self._answers.pop(0) if self._answers else {}
        result: dict[str, DecisionAnswer] = {}
        for key, question in recorded.items():
            if key in scripted:
                result[key] = coerce_answer(scripted[key])
            elif isinstance(question, ChoiceQuestion) and question.options:
                result[key] = DecisionAnswer(value=question.options[0])
            else:
                result[key] = DecisionAnswer(value=False)
        return result


def coerce_answer(raw: RawDecisionAnswer | None) -> DecisionAnswer:
    if raw is None:
        return DecisionAnswer(value=False)
    if isinstance(raw, DecisionAnswer):
        return raw
    if isinstance(raw, bool):
        return DecisionAnswer(value=raw)
    if isinstance(raw, str):
        return DecisionAnswer(value=raw)
    return DecisionAnswer.model_validate(raw)


def is_noul_yes(answer: DecisionAnswer) -> bool:
    if isinstance(answer.value, bool):
        return answer.value
    return str(answer.value).strip().lower() in {"yes", "true", "1"}


def naming_questions(functions: Sequence[LabeledFunction]) -> dict[str, NoulQuestion]:
    """One noul per function. The caller passes ontology functions, not rules."""
    return {
        function.id: NoulQuestion(yes=function.label, no="not this function")
        for function in functions
    }


def fragment_verdict_question() -> dict[str, ChoiceQuestion]:
    return {"verdict": ChoiceQuestion(options=("keep", "change", "delete"))}


def document_present_question(label: str) -> dict[str, NoulQuestion]:
    return {"present": NoulQuestion(yes=label, no="absent")}


__all__ = [
    "ChoiceQuestion",
    "DecisionAnswer",
    "DecisionAnswers",
    "DecisionCall",
    "DecisionClient",
    "DecisionState",
    "DocumentDecisionState",
    "FragmentDecisionState",
    "LabeledFunction",
    "MockDecisionClient",
    "NoulQuestion",
    "Question",
    "RawDecisionAnswer",
    "coerce_answer",
    "document_present_question",
    "fragment_verdict_question",
    "is_noul_yes",
    "naming_questions",
]

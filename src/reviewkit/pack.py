"""Pack: the game a review plays. The profile stays the reviewer's behavior.

A pack carries an ontology, source units, and rules. The ontology names
functions and the vocabulary of a domain; it holds no source text and no
obligation. A rule points at one function and, when it needs a source, at one
unit. The host checks each pass and records the check in a :class:`PassTrace`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reviewkit.models import ReviewScope

_STRICT = ConfigDict(extra="forbid", frozen=True)


class Function(BaseModel):
    model_config = _STRICT

    id: str
    label: str
    attach_to: list[Literal["sentence", "paragraph", "section"]]


class Ontology(BaseModel):
    model_config = _STRICT

    functions: list[Function] = Field(min_length=1)
    source_kinds: list[str] = Field(default_factory=list)
    unit_kinds: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)

    def function_ids(self) -> set[str]:
        return {function.id for function in self.functions}


class SourceUnit(BaseModel):
    model_config = _STRICT

    id: str
    source_id: str
    kind: str
    locator: str
    text: str | None = None
    url: str | None = None
    status: str


class LabelRule(BaseModel):
    model_config = _STRICT

    kind: Literal["label"] = "label"
    id: str
    function_id: str
    scope: Literal["fragment"] = "fragment"


class DefectRule(BaseModel):
    model_config = _STRICT

    kind: Literal["defect"] = "defect"
    id: str
    function_id: str
    scope: Literal["fragment"] = "fragment"
    when: Literal["function_present"] = "function_present"
    source_unit_id: str | None = None


class CloseRule(BaseModel):
    model_config = _STRICT

    kind: Literal["close"] = "close"
    id: str
    function_id: str
    scope: Literal["document"] = "document"
    when: Literal["function_absent"] = "function_absent"
    source_unit_id: str


Rule = Annotated[LabelRule | DefectRule | CloseRule, Field(discriminator="kind")]


class Pack(BaseModel):
    model_config = _STRICT

    id: str
    document_type: str
    ontology: Ontology
    units: dict[str, SourceUnit]
    rules: list[Rule]

    @model_validator(mode="after")
    def _rules_cite_known_ids(self) -> Pack:
        known_functions = self.ontology.function_ids()
        for rule in self.rules:
            if rule.function_id not in known_functions:
                raise ValueError(f"rule {rule.id} cites unknown function {rule.function_id}")
            source_unit_id = getattr(rule, "source_unit_id", None)
            if source_unit_id is not None and source_unit_id not in self.units:
                raise ValueError(f"rule {rule.id} cites unknown unit {source_unit_id}")
        return self


class FunctionTag(BaseModel):
    model_config = _STRICT

    node_id: str
    function_ids: list[str]


class NamingResponse(BaseModel):
    model_config = _STRICT

    tags: list[FunctionTag] = Field(default_factory=list)


class ProcessCheck(BaseModel):
    model_config = _STRICT

    name: str
    passed: bool
    detail: str = ""


class PassTrace(BaseModel):
    model_config = _STRICT

    checks: tuple[ProcessCheck, ...] = ()


def attachable(pack: Pack, scope: ReviewScope) -> bool:
    return scope.value in {"sentence", "paragraph", "section"}


def label_rules(pack: Pack, scope: ReviewScope) -> list[LabelRule]:
    if not attachable(pack, scope):
        return []
    return [rule for rule in pack.rules if isinstance(rule, LabelRule)]


def defect_rules(pack: Pack, function_ids: list[str]) -> list[DefectRule]:
    present = set(function_ids)
    return [
        rule for rule in pack.rules if isinstance(rule, DefectRule) and rule.function_id in present
    ]


def close_rules(pack: Pack, covered: dict[str, list[str]]) -> list[CloseRule]:
    return [
        rule
        for rule in pack.rules
        if isinstance(rule, CloseRule) and not covered.get(rule.function_id)
    ]


def cited_unit(pack: Pack, source_unit_id: str | None) -> SourceUnit | None:
    if source_unit_id is None:
        return None
    return pack.units.get(source_unit_id)


def check_naming(pack: Pack, response: NamingResponse) -> PassTrace:
    known = pack.ontology.function_ids()
    unknown = sorted(
        {
            function_id
            for tag in response.tags
            for function_id in tag.function_ids
            if function_id not in known
        }
    )
    dumped = response.model_dump()
    checks = (
        ProcessCheck(
            name="function_ids_belong_to_ontology",
            passed=not unknown,
            detail=", ".join(unknown),
        ),
        ProcessCheck(
            name="naming_has_no_findings_or_actions",
            passed="findings" not in dumped and "actions" not in dumped,
        ),
    )
    return PassTrace(checks=checks)


def accepted_tags(pack: Pack, response: NamingResponse) -> list[FunctionTag]:
    known = pack.ontology.function_ids()
    return [
        FunctionTag(
            node_id=tag.node_id,
            function_ids=[function_id for function_id in tag.function_ids if function_id in known],
        )
        for tag in response.tags
    ]


class VerdictKind(StrEnum):
    KEEP = "keep"
    CHANGE = "change"
    DELETE = "delete"
    INSERT = "insert"
    MISSING = "missing"


class Verdict(BaseModel):
    model_config = _STRICT

    node_id: str
    kind: VerdictKind
    function_id: str
    reason: str = ""
    confidence: float = 1.0


class VerdictResponse(BaseModel):
    model_config = _STRICT

    verdicts: list[Verdict] = Field(default_factory=list)


class ActionText(BaseModel):
    model_config = _STRICT

    replacement_text: str | None = None


def function_label(pack: Pack, function_id: str) -> str:
    for function in pack.ontology.functions:
        if function.id == function_id:
            return function.label
    return function_id


__all__ = [
    "ActionText",
    "CloseRule",
    "DefectRule",
    "Function",
    "FunctionTag",
    "LabelRule",
    "NamingResponse",
    "Ontology",
    "Pack",
    "PassTrace",
    "ProcessCheck",
    "Rule",
    "SourceUnit",
    "Verdict",
    "VerdictKind",
    "VerdictResponse",
    "accepted_tags",
    "attachable",
    "check_naming",
    "cited_unit",
    "close_rules",
    "defect_rules",
    "function_label",
    "label_rules",
]

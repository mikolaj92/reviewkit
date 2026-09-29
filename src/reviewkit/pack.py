"""Pack: the game a review plays. The profile stays the reviewer's behavior.

A pack is a separate object from instructions.md, external_review_context, and
profile.toml. The ontology names functions; it holds no source text and no
obligation. Units hold source text. A rule points at one function and, when it
needs a source, at one unit. The host checks each pass and records the check in
a :class:`PassTrace`.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reviewkit.models import ReviewScope

_STRICT = ConfigDict(extra="forbid", frozen=True)

type FunctionAttachTo = Literal["sentence", "paragraph", "section"]
type RuleKind = Literal["label", "close", "defect"]
type RuleScope = Literal["fragment", "document"]
type RuleWhen = Literal["always", "function_present", "function_absent"]


class Function(BaseModel):
    model_config = _STRICT

    id: str
    label: str
    attach_to: list[FunctionAttachTo]


class Ontology(BaseModel):
    model_config = _STRICT

    functions: list[Function] = Field(min_length=1)

    def function_ids(self) -> set[str]:
        return {function.id for function in self.functions}


class SourceUnit(BaseModel):
    model_config = _STRICT

    id: str
    source_id: str
    locator: str
    text: str | None = None
    url: str | None = None
    force: str


class Rule(BaseModel):
    model_config = _STRICT

    id: str
    kind: RuleKind
    function_id: str
    scope: RuleScope
    when: RuleWhen
    source_unit_id: str | None = None


class Pack(BaseModel):
    model_config = _STRICT

    ontology: Ontology
    rules: list[Rule]
    units: dict[str, SourceUnit]

    @model_validator(mode="after")
    def _rules_cite_known_ids(self) -> Pack:
        known_functions = self.ontology.function_ids()
        for rule in self.rules:
            if rule.function_id not in known_functions:
                raise ValueError(f"rule {rule.id} cites unknown function {rule.function_id}")
            if rule.source_unit_id is not None and rule.source_unit_id not in self.units:
                raise ValueError(f"rule {rule.id} cites unknown unit {rule.source_unit_id}")
            if rule.kind == "label" and rule.scope != "fragment":
                raise ValueError(f"rule {rule.id} label must be fragment scope")
            if rule.kind == "defect" and rule.scope != "fragment":
                raise ValueError(f"rule {rule.id} defect must be fragment scope")
            if rule.kind == "close" and rule.scope != "document":
                raise ValueError(f"rule {rule.id} close must be document scope")
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


def naming_functions(pack: Pack, scope: ReviewScope) -> list[Function]:
    """Name every sentence, paragraph, section, and document against the dictionary."""
    if scope not in {
        ReviewScope.SENTENCE,
        ReviewScope.PARAGRAPH,
        ReviewScope.SECTION,
        ReviewScope.DOCUMENT,
    }:
        return []
    return list(pack.ontology.functions)


def judge_rules(
    pack: Pack,
    scope: ReviewScope,
    function_ids: Sequence[str],
    covered: dict[str, list[str]],
) -> list[Rule]:
    """Scan-2 rules whose when/scope match. Document-scope rules never leave the document."""
    present = set(function_ids)
    fragment = scope is not ReviewScope.DOCUMENT
    matched: list[Rule] = []
    for rule in pack.rules:
        if rule.kind == "label":
            continue
        if fragment:
            if rule.scope != "fragment" or rule.kind == "close":
                continue
            if rule.when == "function_absent":
                continue
            if rule.when == "function_present" and rule.function_id not in present:
                continue
            matched.append(rule)
            continue
        if rule.scope != "document":
            continue
        if rule.when == "function_absent" and covered.get(rule.function_id):
            continue
        if rule.when == "function_present" and not covered.get(rule.function_id):
            continue
        matched.append(rule)
    return matched


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
    "Function",
    "FunctionAttachTo",
    "FunctionTag",
    "NamingResponse",
    "Ontology",
    "Pack",
    "PassTrace",
    "ProcessCheck",
    "Rule",
    "RuleKind",
    "RuleScope",
    "RuleWhen",
    "SourceUnit",
    "Verdict",
    "VerdictKind",
    "accepted_tags",
    "check_naming",
    "cited_unit",
    "function_label",
    "judge_rules",
    "naming_functions",
]

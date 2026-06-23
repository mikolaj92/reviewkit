"""Optional Dike-to-ReviewKit action mappers.

The adapter is intentionally structural: it accepts dictionaries or Pydantic/dataclass-like
objects and does not import Dike. This keeps ReviewKit generic while giving Fala a stable bridge.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import Any

from reviewkit.models import (
    ActionStatus,
    EvidenceRef,
    ReviewAction,
    ReviewActionType,
    ReviewReference,
    ReviewScope,
)


def actions_from_dike_report(report: Mapping[str, Any] | object) -> list[ReviewAction]:
    payload = _as_mapping(report)
    findings = _as_list(payload.get("findings"))
    return [_action_from_finding(finding) for finding in findings]


def action_from_dike_paragraph_assessment(
    assessment: Mapping[str, Any] | object,
) -> ReviewAction:
    payload = _as_mapping(assessment)
    index = int(payload.get("index", 0) or 0)
    node_id = f"p{index}" if index > 0 else "document"
    apply_to_corrected = bool(payload.get("apply_to_corrected", False))
    requires_human_decision = bool(payload.get("requires_human_review", False))
    action_type = (
        ReviewActionType.REPLACE
        if payload.get("action_type") == "replace_paragraph"
        else ReviewActionType.COMMENT
    )

    return ReviewAction(
        id=f"dike-paragraph-{index or 'document'}",
        scope=ReviewScope.PARAGRAPH if index > 0 else ReviewScope.DOCUMENT,
        action_type=action_type,
        node_id=node_id,
        original_text=_optional_str(payload.get("text")),
        replacement_text=_optional_str(payload.get("proposed_text")),
        comment=_optional_str(payload.get("suggestion")),
        reason=_optional_str(payload.get("issue")),
        severity=str(payload.get("severity", "medium")),
        status=ActionStatus.NOT_APPLIED,
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        category=_optional_str(payload.get("issue_type")),
        priority=_optional_str(payload.get("priority")),
        requires_human_decision=requires_human_decision,
        apply_to_corrected=apply_to_corrected,
        policy_reason=_optional_str(payload.get("correction_policy_reason")),
        source_system="dike",
        tags=["dike", "paragraph_assessment"],
        metadata={"assessment": _optional_str(payload.get("assessment")) or ""},
    )


def _action_from_finding(finding: Mapping[str, Any] | object) -> ReviewAction:
    payload = _as_mapping(finding)
    evidence_refs = [_evidence_ref(item) for item in _as_list(payload.get("evidence_refs"))]
    references = [_reference(item) for item in _as_list(payload.get("legal_basis"))]
    missing_elements = _as_list(payload.get("missing_elements"))
    node_id = _node_id_from_evidence(evidence_refs)
    recommendation = _as_mapping(payload.get("recommendation") or {})

    return ReviewAction(
        id=f"dike-finding-{payload.get('rule_code', node_id)}",
        scope=ReviewScope.PARAGRAPH if node_id.startswith("p") else ReviewScope.DOCUMENT,
        action_type=ReviewActionType.RISK if _is_high_risk(payload) else ReviewActionType.COMMENT,
        node_id=node_id,
        original_text=_first_excerpt(evidence_refs),
        comment=_optional_str(payload.get("summary")),
        reason=_optional_str(payload.get("title")),
        severity=str(payload.get("severity", "medium")),
        status=ActionStatus.NOT_APPLIED,
        confidence=_confidence_from_trace(payload),
        category=_optional_str(payload.get("rule_code")) or "legal_risk",
        requires_human_decision=True,
        source_system="dike",
        tags=["dike", "finding"],
        evidence_refs=evidence_refs,
        references=references,
        metadata={
            "recommendation_code": _optional_str(recommendation.get("code")) or "",
            "recommendation_title": _optional_str(recommendation.get("title")) or "",
            "recommendation_action": _optional_str(recommendation.get("action")) or "",
            "missing_elements": missing_elements,
        },
    )


def _as_mapping(value: Mapping[str, Any] | object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, Mapping) else {}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _as_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _evidence_ref(value: object) -> EvidenceRef:
    payload = _as_mapping(value)
    return EvidenceRef(
        segment_id=_optional_str(payload.get("segment_id")),
        locator=_optional_str(payload.get("locator") or payload.get("reference")),
        excerpt=_optional_str(payload.get("excerpt")),
        source="dike",
        metadata={
            key: item
            for key, item in payload.items()
            if key not in {"segment_id", "locator", "excerpt"}
        },
    )


def _reference(value: object) -> ReviewReference:
    payload = _as_mapping(value)
    source = _optional_str(payload.get("source")) or "Dike legal basis"
    article = _optional_str(payload.get("article"))
    clause = _optional_str(payload.get("clause"))
    label = " ".join(part for part in [source, article, clause] if part)
    return ReviewReference(
        source=source,
        label=label or source,
        note=_optional_str(payload.get("note")),
        metadata={
            key: item
            for key, item in payload.items()
            if key not in {"source", "article", "clause", "note"}
        },
    )


def _node_id_from_evidence(evidence_refs: list[EvidenceRef]) -> str:
    for evidence in evidence_refs:
        for value in (evidence.locator, evidence.segment_id):
            if not value:
                continue
            parsed = _paragraph_node_from_dike_locator(value)
            if parsed:
                return parsed
    return "document"


def _paragraph_node_from_dike_locator(value: str) -> str | None:
    parts = value.split("#", 1)[0].split(":")
    if len(parts) >= 3 and parts[-2] == "p":
        try:
            return f"p{int(parts[-1]) + 1}"
        except ValueError:
            return None
    return None


def _first_excerpt(evidence_refs: list[EvidenceRef]) -> str | None:
    for evidence in evidence_refs:
        if evidence.excerpt:
            return evidence.excerpt
    return None


def _confidence_from_trace(payload: Mapping[str, Any]) -> float:
    trace = _as_mapping(payload.get("trace") or {})
    reasoning = _as_mapping(trace.get("reasoning_trace") or {})
    confidence = reasoning.get("confidence")
    if isinstance(confidence, int | float):
        return float(confidence)
    return 1.0 if payload.get("evidence_refs") else 0.0


def _is_high_risk(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("severity", "")).lower() in {"high", "critical"}


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None

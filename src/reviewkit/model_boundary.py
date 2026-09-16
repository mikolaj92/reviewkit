"""Model-facing projections for ReviewKit's host-owned audit boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reviewkit.models import ReviewAction, ReviewFinding

_MODEL_AUDIT_SCHEMA_FIELDS: dict[str, frozenset[str]] = {
    "ReviewFinding": frozenset({"lineage", "reconciliation"}),
    "ReviewAction": frozenset({"status", "policy_reason", "lineage"}),
}
HOST_OWNED_METADATA_KEYS = frozenset(
    {"merged_finding_ids", "reconciliation_request_id", "blocked_from_corrected"}
)


def strip_model_audit_fields(schema: dict[str, Any]) -> dict[str, Any]:
    """Hide host-owned audit fields from a response schema sent to the model.

    The public result models remain complete and continue to carry the audit trail. Their
    response-envelope schema is the model boundary, so a provider is not prompted to
    reproduce host-generated lineage, status, or policy decisions on a later pass.
    """
    definitions = schema.get("$defs", {})
    candidates = [schema]
    if isinstance(definitions, dict):
        candidates.extend(value for value in definitions.values() if isinstance(value, dict))

    for candidate in candidates:
        title = candidate.get("title")
        excluded = (
            _MODEL_AUDIT_SCHEMA_FIELDS.get(title)
            if isinstance(title, str)
            else None
        )
        if not excluded:
            continue
        properties = candidate.get("properties")
        if isinstance(properties, dict):
            for field_name in excluded:
                properties.pop(field_name, None)
        required = candidate.get("required")
        if isinstance(required, list):
            candidate["required"] = [name for name in required if name not in excluded]

    definitions = schema.get("$defs")
    if isinstance(definitions, dict):
        reachable: set[str] = set()

        def _references(value: Any) -> set[str]:
            if isinstance(value, dict):
                mapping_refs: set[str] = set()
                ref = value.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    mapping_refs.add(ref.removeprefix("#/$defs/"))
                for child in value.values():
                    mapping_refs.update(_references(child))
                return mapping_refs
            if isinstance(value, list):
                sequence_refs: set[str] = set()
                for child in value:
                    sequence_refs.update(_references(child))
                return sequence_refs
            return set()

        pending = _references({key: value for key, value in schema.items() if key != "$defs"})
        while pending:
            name = pending.pop()
            if name in reachable or name not in definitions:
                continue
            reachable.add(name)
            pending.update(_references(definitions[name]))
        for name in tuple(definitions):
            if name not in reachable:
                definitions.pop(name)
    return schema


def model_facing_finding_payload(finding: ReviewFinding) -> dict[str, Any]:
    """Project a finding into semantic context suitable for a later model prompt."""
    payload = finding.model_dump(
        mode="json",
        exclude={"lineage", "reconciliation"},
    )
    payload["metadata"] = strip_host_owned_metadata(payload.get("metadata"))
    return payload


def model_facing_action_payload(action: ReviewAction) -> dict[str, Any]:
    """Project an action without host-owned status or audit enrichment."""
    payload = action.model_dump(
        mode="json",
        by_alias=True,
        exclude={"status", "policy_reason", "lineage"},
    )
    payload["metadata"] = strip_host_owned_metadata(payload.get("metadata"))
    return payload


def strip_host_owned_metadata(metadata: Any) -> dict[str, Any]:
    """Remove ReviewKit-owned metadata while preserving arbitrary substantive fields."""
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value for key, value in metadata.items() if key not in HOST_OWNED_METADATA_KEYS
    }


__all__ = [
    "model_facing_action_payload",
    "model_facing_finding_payload",
    "strip_host_owned_metadata",
    "strip_model_audit_fields",
]

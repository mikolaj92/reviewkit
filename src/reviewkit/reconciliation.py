"""Bounded, deterministic whole-to-local reconciliation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from reviewkit.models import (
    FindingLineageEvent,
    FindingReconciliation,
    ReconciliationDisposition,
    ReconciliationRequest,
    ReviewFinding,
    ReviewScope,
)
from reviewkit.plant import DocNode


def select_reconciliation_targets(
    requests: Iterable[ReconciliationRequest],
    scanned_nodes: Mapping[str, DocNode],
    *,
    max_nodes: int,
) -> list[tuple[ReconciliationRequest, DocNode]]:
    """Resolve model requests only against the host's prior scan, within budget.

    Invalid, document-level, duplicate, and over-budget targets are ignored.  In
    particular, no locator supplied by the model is ever interpreted as a path.
    """
    selected: list[tuple[ReconciliationRequest, DocNode]] = []
    seen: set[str] = set()
    for request in requests:
        node_id = request.target.node_id
        node = scanned_nodes.get(node_id or "")
        scope = node.scope() if node is not None else None
        if (
            node is None
            or scope is None
            or scope == ReviewScope.DOCUMENT
            or node_id in seen
            or len(selected) >= max_nodes
        ):
            continue
        source_text = str(getattr(getattr(node, "inner", node), "text", "") or "")
        locator = request.target
        if locator.text_hash and locator.text_hash != locator.hash_text(source_text):
            continue
        seen.add(node_id)
        selected.append((request, node))
    return selected


def reconcile_findings(
    findings: list[ReviewFinding],
    rereviewed: Iterable[tuple[ReconciliationRequest, ReviewFinding]],
) -> list[ReviewFinding]:
    """Merge rereview output without silently deleting the previous finding."""
    result = list(findings)
    by_id = {finding.finding_id: index for index, finding in enumerate(result)}

    for request, after in rereviewed:
        prior_id = after.reconciles_finding_id
        disposition = after.reconciliation_disposition
        if not prior_id or prior_id not in by_id or disposition is None:
            result.append(after)
            by_id[after.finding_id] = len(result) - 1
            continue

        index = by_id[prior_id]
        before = result[index]
        record = FindingReconciliation(
            request_id=request.request_id,
            disposition=disposition,
            reason=request.reason,
            target_node_id=request.target.node_id or after.node_id,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
        )
        event = FindingLineageEvent(
            kind="reconciliation",
            scope=_scope_for_node_id(after.node_id),
            node_id=after.node_id,
            locator=request.target,
            parent_event_ids=tuple(event.event_id for event in before.lineage),
            evidence_refs=tuple(str(item) for item in request.evidence),
            context_refs=(request.request_id,),
            decision=disposition.value,
        )
        if disposition == ReconciliationDisposition.CONFLICT:
            after.reconciliation = record
            after.lineage = (*before.lineage, *after.lineage, event)
            result.append(after)
            by_id[after.finding_id] = len(result) - 1
            continue

        merged = after.model_copy(deep=True)
        merged.finding_id = before.finding_id
        merged.reconciliation = record
        merged.lineage = (*before.lineage, *after.lineage, event)
        merged.metadata = {
            **before.metadata,
            **after.metadata,
            "reconciliation_request_id": request.request_id,
            "reconciliation_disposition": disposition.value,
        }
        result[index] = merged

    return result


def _scope_for_node_id(node_id: str) -> ReviewScope | None:
    for scope in (ReviewScope.SENTENCE, ReviewScope.PARAGRAPH, ReviewScope.SECTION):
        if scope.value in node_id.lower():
            return scope
    return None

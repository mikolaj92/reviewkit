"""Demote overlapping and opaque-content edits to CONFLICT."""

from __future__ import annotations

from reviewkit.action_target import actions_for_paragraph
from reviewkit.document import ReviewDocument
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType
from reviewkit.policy import WRITING_ACTIONS


def demote_overlapping_actions(
    document: ReviewDocument, actions: list[ReviewAction]
) -> list[ReviewAction]:
    """Escalate APPLIED writing edits whose char ranges overlap on the same node.

    Each action is validated against the original node text in isolation, so two
    edits that individually pass can still target overlapping spans of one node.
    The text-application sweep would then overwrite one edit with the other,
    silently losing it. Overlapping edits are ambiguous, so demote every action
    in an overlapping cluster to CONFLICT rather than guessing which one wins.
    """
    ranges_by_node: dict[str, list[tuple[int, int, int]]] = {}
    for index, action in enumerate(actions):
        if action.status != ActionStatus.APPLIED or action.action_type not in WRITING_ACTIONS:
            continue
        node_text = document.get_node_text(action.node_id)
        if node_text is None:
            continue
        span = _applied_char_range(node_text, action)
        if span is None:
            continue
        ranges_by_node.setdefault(action.node_id, []).append((span[0], span[1], index))

    overlapping: set[int] = set()
    for spans in ranges_by_node.values():
        overlapping |= _overlapping_span_indices(spans)
    if not overlapping:
        return actions

    reason = "overlapping edit range conflicts with another edit on the same node"
    result = list(actions)
    for index in overlapping:
        action = result[index]
        result[index] = action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, reason),
                "policy_reason": reason,
            }
        )
    return result


def _overlapping_span_indices(spans: list[tuple[int, int, int]]) -> set[int]:
    """Third-element indices of ``(start, end, index)`` spans that overlap.

    A zero-width span (``start == end``) only overlaps a range that strictly
    contains its point, never one it merely abuts - the strict ``start < cluster_end``
    test keeps abutting and zero-width-at-boundary edits compatible.
    """
    overlapping: set[int] = set()
    cluster: list[int] = []
    cluster_end = 0
    for start, end, index in sorted(spans):
        if cluster and start < cluster_end:
            overlapping.update(cluster)
            overlapping.add(index)
            cluster.append(index)
            cluster_end = max(cluster_end, end)
        else:
            cluster = [index]
            cluster_end = end
    return overlapping


def demote_cross_scope_overlaps(
    document: ReviewDocument, actions: list[ReviewAction]
) -> list[ReviewAction]:
    """Escalate APPLIED edits that overlap once resolved into the same paragraph.

    ``prepare_actions`` runs the overlap guard within a single LLM response, grouped
    by ``node_id``, so it never compares edits produced at different review scopes
    (sentence/paragraph/section/document) that ultimately land on one paragraph. Both
    renderers apply corrections per paragraph (see ``actions_for_paragraph``), rebasing
    sentence offsets and anchoring scope-level edits, so two such edits with overlapping
    spans would silently clobber each other. Resolve every action into the paragraph it
    edits and demote overlapping clusters in that shared coordinate system.

    Demotion is tracked by list position, never by ``action.id``: ids are chosen by the
    LLM and (via ``extra_actions``) by independent callers, so nothing guarantees their
    uniqueness across sources. Keying the demotion on ids would collaterally flip an
    unrelated, non-overlapping edit that merely reuses an id from an overlapping cluster.
    """
    to_demote: set[int] = set()
    for paragraph in document.iter_paragraphs():
        spans: list[tuple[int, int, int]] = []
        for position, action in enumerate(actions):
            if action.status != ActionStatus.APPLIED or action.action_type not in WRITING_ACTIONS:
                continue
            for resolved in actions_for_paragraph(document, paragraph, [action]):
                span = _applied_char_range(paragraph.text, resolved)
                if span is not None:
                    spans.append((span[0], span[1], position))
        to_demote |= _overlapping_span_indices(spans)
    if not to_demote:
        return actions

    reason = "overlapping edit range conflicts with another edit on the same paragraph"
    result: list[ReviewAction] = []
    for position, action in enumerate(actions):
        if position in to_demote:
            result.append(
                action.model_copy(
                    update={
                        "status": ActionStatus.CONFLICT,
                        "reason": _append_reason(action.reason, reason),
                        "policy_reason": reason,
                    }
                )
            )
        else:
            result.append(action)
    return result


def demote_edits_over_opaque_content(
    document: ReviewDocument, actions: list[ReviewAction]
) -> list[ReviewAction]:
    """Escalate APPLIED edits whose span covers non-text inline content.

    ``paragraph.text`` includes the visible characters of inline content the
    renderers cannot edit (tabs/breaks, hyperlink and field text, ...), so text
    validation happily anchors an edit inside it. Neither renderer can honor such
    an edit: the opaque XML survives untouched, so the corrected output keeps (or
    misplaces) the covered content and the reviewed output would mark the wrong
    span. Fail closed at prepare time: the action becomes CONFLICT, both artifacts
    still render (the edit surfaces as a labelled comment) and the report is honest,
    instead of aborting the whole run with a RenderIntegrityError.
    """
    to_demote: set[int] = set()
    for paragraph in document.iter_paragraphs():
        if not paragraph.opaque_ranges:
            continue
        for position, action in enumerate(actions):
            if position in to_demote:
                continue
            if action.status != ActionStatus.APPLIED or action.action_type not in WRITING_ACTIONS:
                continue
            for resolved in actions_for_paragraph(document, paragraph, [action]):
                span = _applied_char_range(paragraph.text, resolved)
                if span is not None and _span_touches_opaque(span, paragraph.opaque_ranges):
                    to_demote.add(position)
                    break
    if not to_demote:
        return actions

    reason = (
        "edit range covers non-text inline content (tab/break/hyperlink/field/...) "
        "that cannot be edited deterministically"
    )
    result = list(actions)
    for position in to_demote:
        action = result[position]
        result[position] = action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, reason),
                "policy_reason": reason,
            }
        )
    return result


def _span_touches_opaque(span: tuple[int, int], opaque_ranges: list[tuple[int, int]]) -> bool:
    start, end = span
    for opaque_start, opaque_end in opaque_ranges:
        if start == end:
            # Zero-width insertion: only conflicts when the point falls strictly
            # inside opaque content; abutting its boundary is a valid insert.
            if opaque_start < start < opaque_end:
                return True
        elif max(start, opaque_start) < min(end, opaque_end):
            return True
    return False


def _applied_char_range(node_text: str, action: ReviewAction) -> tuple[int, int] | None:
    """Span of ``node_text`` an APPLIED writing action mutates, if determinable."""
    locator = action.locator
    if locator and locator.char_start is not None and locator.char_end is not None:
        if action.action_type == ReviewActionType.INSERT_AFTER:
            # A zero-width insertion at char_end touches no existing character, so it only
            # conflicts with an edit spanning that exact point - not with edits that merely
            # sit inside its anchor span, which are compatible and must not be false-demoted.
            return locator.char_end, locator.char_end
        if action.action_type == ReviewActionType.INSERT_BEFORE:
            # Symmetric to INSERT_AFTER: INSERT_BEFORE inserts at char_start (see
            # apply_action_to_text), so its footprint is that zero-width point, not the
            # whole anchor span. Reporting the full span false-demotes compatible edits
            # that merely sit inside the anchor.
            return locator.char_start, locator.char_start
        return locator.char_start, locator.char_end
    original = action.original_text
    if original and original in node_text:
        # First occurrence, exactly like apply_action_to_text's str.replace(..., 1):
        # when a profile allows non-unique anchors, this is the span that actually
        # gets edited, so the overlap guards must reason about the same occurrence.
        start = node_text.find(original)
        if action.action_type == ReviewActionType.INSERT_AFTER:
            return start + len(original), start + len(original)
        if action.action_type == ReviewActionType.INSERT_BEFORE:
            return start, start
        return start, start + len(original)
    return None


def _append_reason(existing: str | None, addition: str) -> str:
    if existing:
        return f"{existing}; {addition}"
    return addition

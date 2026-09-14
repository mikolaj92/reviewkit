"""comparison direct seams for DOCX provenance attribution."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from reviewkit.comment_formatter import format_action_comment
from reviewkit.comparison_models import (
    ChangeProvenance,
    ProvenanceDiagnostic,
    ProvenanceStatus,
)
from reviewkit.comparison_verification import (
    _DELETE_ACTIONS,
    _INSERT_ACTIONS,
    _REPLACE_ACTIONS,
    _blocked_by_diagnostic,
    _empty_rows,
    _MappedAction,
)
from reviewkit.models import ActionStatus, ReviewAction
from reviewkit.policy import WRITING_ACTIONS

if TYPE_CHECKING:
    from docxtor import (
        DocumentBlock,
        DocumentComment,
        DocxDocumentComparison,
        RevisionEvent,
        RevisionReference,
        TextChange,
    )


@dataclass(frozen=True)
class _ActionMatch:
    mapped: _MappedAction
    output_span: tuple[int, int] | None
    revision_ids: tuple[str, ...]


@dataclass(frozen=True)
class _DirectResult:
    rows: dict[str, ChangeProvenance]
    matched_revisions: dict[str, tuple[str, RevisionReference]]
    matched_comments: dict[str, str]
    source_review_comments: tuple[DocumentComment, ...]
    action_review_comments: tuple[tuple[str, DocumentComment], ...]
    action_matches: dict[str, _ActionMatch]


def _attribute_direct(
    comparison: DocxDocumentComparison,
    mapped: dict[str, _MappedAction | None],
    *,
    diagnostics: tuple[ProvenanceDiagnostic, ...],
) -> _DirectResult:
    rows = _empty_rows(comparison)
    source_reviews: list[DocumentComment] = []
    action_comments: list[tuple[str, DocumentComment]] = []
    matched_comments: dict[str, str] = {}
    action_matches: dict[str, _ActionMatch] = {}
    _mark_source_comments_direct(comparison, rows, source_reviews)
    revision_assignments, revision_matches = _match_revisions(comparison, mapped, rows, diagnostics)
    action_matches.update(revision_matches)
    _match_text_changes(comparison, mapped, action_matches, rows, diagnostics)
    matched_comments = _match_action_comments(
        comparison,
        mapped,
        action_matches,
        rows,
        diagnostics,
        source_reviews,
        action_comments,
    )
    return _DirectResult(
        rows,
        revision_assignments,
        matched_comments,
        tuple(source_reviews),
        tuple(action_comments),
        action_matches,
    )


def _match_revisions(
    comparison: DocxDocumentComparison,
    mapped: dict[str, _MappedAction | None],
    rows: dict[str, ChangeProvenance],
    diagnostics: tuple[ProvenanceDiagnostic, ...],
) -> tuple[dict[str, tuple[str, RevisionReference]], dict[str, _ActionMatch]]:
    expected_output_spans = _expected_action_output_spans(mapped)
    candidates: dict[str, list[tuple[str, RevisionEvent, tuple[int, int] | None]]] = defaultdict(
        list
    )
    revision_events = [
        event for event in comparison.revision_events if event.status.value == "introduced"
    ]
    for action_id, action_map in mapped.items():
        if (
            action_map is None
            or action_id not in expected_output_spans
            or not _is_trackable(action_map.target.action)
        ):
            continue
        action = action_map.target.action
        if action.new_paragraph:
            continue
        expected: list[tuple[str, str, int | None, int | None]] = []
        if action.action_type in _REPLACE_ACTIONS | _DELETE_ACTIONS:
            expected.append(("del", action_map.target.original, action_map.start, action_map.end))
        if action.action_type in _REPLACE_ACTIONS | _INSERT_ACTIONS and action.replacement_text:
            expected.append(("ins", action.replacement_text, None, None))
        if not expected:
            continue
        matches: list[tuple[RevisionEvent, tuple[int, int] | None]] = []
        complete = True
        for kind, text, start, end in expected:
            possible: list[tuple[RevisionEvent, tuple[int, int] | None]] = []
            for event in revision_events:
                ref = event.right
                if (
                    ref is None
                    or ref.kind != kind
                    or ref.text != text
                    or ref.container_id != action_map.target.locator
                    or ref.pair_id != action_map.pair_id
                ):
                    continue
                span = (
                    _revision_accepted_span(action_map.right_block, ref) if kind == "ins" else None
                )
                if kind == "ins" and span != expected_output_spans[action_id]:
                    continue
                if kind == "del" and (ref.start_offset != start or ref.end_offset != end):
                    continue
                if kind == "ins" and span is None:
                    continue
                possible.append((event, span))
            if len(possible) != 1:
                complete = False
                break
            matches.append(possible[0])
        if complete and matches:
            candidates[action_id] = [(action_id, event, span) for event, span in matches]

    owners: dict[str, set[str]] = defaultdict(set)
    for action_id, action_candidates in candidates.items():
        for _owner, event, _span in action_candidates:
            owners[event.change_id].add(action_id)

    event_to_action: dict[str, tuple[str, RevisionReference]] = {}
    action_matches: dict[str, _ActionMatch] = {}
    for action_id, action_candidates in candidates.items():
        if any(len(owners[event.change_id]) != 1 for _owner, event, _span in action_candidates):
            continue
        action_map = mapped[action_id]
        assert action_map is not None
        output_spans = [
            span
            for _owner, event, span in action_candidates
            if event.right is not None and event.right.kind == "ins"
        ]
        output_span = output_spans[0] if len(output_spans) == 1 else None
        if _blocked_by_diagnostic(
            diagnostics,
            action_map.target.locator,
            "revision",
            pair_id=action_map.pair_id,
        ):
            continue
        for _owner, event, _span in action_candidates:
            assert event.right is not None
            event_to_action[event.change_id] = (action_id, event.right)
            rows[event.change_id] = ChangeProvenance(
                event.change_id,
                "revision",
                ProvenanceStatus.VERIFIED_ACTION,
                (action_id,),
                ("hash_chain_verified", "physical_locator_matched", "revision_payload_matched"),
            )
        action_matches[action_id] = _ActionMatch(
            action_map,
            output_span,
            tuple(event.change_id for _owner, event, _span in action_candidates),
        )
    return event_to_action, action_matches


def _expected_action_output_spans(
    mapped: dict[str, _MappedAction | None],
) -> dict[str, tuple[int, int] | None]:
    """Return action spans only when mapped edits reproduce each accepted block exactly."""
    groups: dict[str, list[tuple[str, _MappedAction]]] = defaultdict(list)
    for action_id, action_map in mapped.items():
        if (
            action_map is not None
            and _is_trackable(action_map.target.action)
            and not action_map.target.action.new_paragraph
        ):
            groups[action_map.left_block.id].append((action_id, action_map))

    verified: dict[str, tuple[int, int] | None] = {}
    for actions in groups.values():
        first = actions[0][1]
        source_text = first.left_block.text
        edits: list[tuple[int, int, str, str]] = []
        for action_id, action_map in actions:
            action = action_map.target.action
            if action.action_type in _INSERT_ACTIONS:
                point = action_map.insertion_point
                if point is None:
                    edits = []
                    break
                start = end = point
            elif action.action_type in _REPLACE_ACTIONS | _DELETE_ACTIONS:
                start, end = action_map.start, action_map.end
            else:
                continue
            edits.append((start, end, action.replacement_text or "", action_id))

        if not edits:
            continue
        edits.sort(key=lambda item: (item[0], item[1]))
        previous_start = -1
        previous_end = 0
        valid = True
        for start, end, _replacement, _action_id in edits:
            if (
                start < 0
                or end < start
                or end > len(source_text)
                or start < previous_end
                or start == previous_start
            ):
                valid = False
                break
            previous_start, previous_end = start, end
        if not valid:
            continue

        output_parts: list[str] = []
        output_spans: dict[str, tuple[int, int] | None] = {}
        output_length = 0
        cursor = 0
        for start, end, replacement, action_id in edits:
            unchanged = source_text[cursor:start]
            output_parts.append(unchanged)
            output_length += len(unchanged)
            span_start = output_length
            output_parts.append(replacement)
            output_length += len(replacement)
            output_spans[action_id] = (span_start, output_length) if replacement else None
            cursor = end
        output_parts.append(source_text[cursor:])
        if "".join(output_parts) == first.right_block.text:
            verified.update(output_spans)
    return verified


def _revision_accepted_span(
    block: DocumentBlock, reference: RevisionReference
) -> tuple[int, int] | None:
    spans = sorted(
        (
            span
            for span in block.spans
            if span.role == "insertion"
            and span.revision_kind == "ins"
            and span.start_offset >= reference.start_offset
            and span.end_offset <= reference.end_offset
        ),
        key=lambda span: span.start_offset,
    )
    if not spans or spans[0].start_offset != reference.start_offset:
        return None
    raw_end = spans[0].end_offset
    accepted_start = spans[0].accepted_start_offset
    accepted_end = spans[0].accepted_end_offset
    text_parts = [spans[0].text]
    for span in spans[1:]:
        if span.start_offset != raw_end or span.accepted_start_offset != accepted_end:
            return None
        raw_end = span.end_offset
        accepted_end = span.accepted_end_offset
        text_parts.append(span.text)
    if (
        raw_end != reference.end_offset
        or accepted_start is None
        or accepted_end is None
        or "".join(text_parts) != reference.text
    ):
        return None
    return accepted_start, accepted_end


def _match_text_changes(
    comparison: DocxDocumentComparison,
    mapped: dict[str, _MappedAction | None],
    action_matches: dict[str, _ActionMatch],
    rows: dict[str, ChangeProvenance],
    diagnostics: tuple[ProvenanceDiagnostic, ...],
) -> dict[str, str]:
    assignments: dict[str, str] = {}
    candidates: dict[str, list[str]] = defaultdict(list)
    for action_id, match in action_matches.items():
        for change in comparison.text_changes:
            if _text_change_within_action(change, match):
                if _blocked_by_diagnostic(
                    diagnostics,
                    match.mapped.target.locator,
                    "text",
                    pair_id=match.mapped.pair_id,
                ):
                    continue
                candidates[change.change_id].append(action_id)

    # The corrected artifact has accepted text but no revision wrappers. Bind its
    # replacement range only when the exact action result occurs once in the mapped
    # physical paragraph.
    expected_output_spans = _expected_action_output_spans(mapped)
    for action_id, action_map in mapped.items():
        if action_map is None or action_id in action_matches:
            continue
        if action_id not in expected_output_spans:
            continue
        action = action_map.target.action
        if not _can_accept(action) or action.new_paragraph:
            continue
        if any(event.status.value == "introduced" for event in comparison.revision_events):
            continue
        if _is_deletion(action):
            output_span = None
        elif action.replacement_text:
            output_span = expected_output_spans[action_id]
            if output_span is None:
                continue
        else:
            continue
        match = _ActionMatch(action_map, output_span, ())
        action_matches[action_id] = match
        for change in comparison.text_changes:
            if _text_change_within_action(change, match) and not _blocked_by_diagnostic(
                diagnostics,
                action_map.target.locator,
                "text",
                pair_id=action_map.pair_id,
            ):
                candidates[change.change_id].append(action_id)

    for change_id, action_ids in candidates.items():
        unique = tuple(sorted(set(action_ids)))
        if len(unique) != 1:
            continue
        action_id = unique[0]
        assignments[change_id] = action_id
        rows[change_id] = ChangeProvenance(
            change_id,
            "text",
            ProvenanceStatus.VERIFIED_ACTION,
            (action_id,),
            ("hash_chain_verified", "physical_locator_matched", "text_span_contained_in_action"),
        )
    return assignments


def _text_change_within_action(change: TextChange, match: _ActionMatch) -> bool:
    mapped = match.mapped
    left, right = change.left, change.right
    if left is not None and (
        left.pair_id != mapped.pair_id or left.block_id != mapped.left_block.id
    ):
        return False
    if right is not None and (
        right.pair_id != mapped.pair_id or right.block_id != mapped.right_block.id
    ):
        return False
    action_type = mapped.target.action.action_type
    if _is_deletion(mapped.target.action):
        if left is None or left.pair_id != mapped.pair_id or left.block_id != mapped.left_block.id:
            return False
        if not _contains((left.start_offset, left.end_offset), (mapped.start, mapped.end)):
            return False
        relative_start = mapped.start - left.start_offset
        relative_end = mapped.end - left.start_offset
        if left.text[relative_start:relative_end] != mapped.target.original:
            return False
        unchanged_text = left.text[:relative_start] + left.text[relative_end:]
        if right is None:
            return unchanged_text == ""
        return (
            right.pair_id == mapped.pair_id
            and right.block_id == mapped.right_block.id
            and right.start_offset == left.start_offset
            and right.text == unchanged_text
            and right.end_offset == left.end_offset - len(mapped.target.original)
        )
    if action_type in _INSERT_ACTIONS:
        return (
            left is None
            and right is not None
            and match.output_span is not None
            and _contains(match.output_span, (right.start_offset, right.end_offset))
        )
    return (
        left is not None
        and right is not None
        and _contains((mapped.start, mapped.end), (left.start_offset, left.end_offset))
        and match.output_span is not None
        and _contains(match.output_span, (right.start_offset, right.end_offset))
    )


def _match_action_comments(
    comparison: DocxDocumentComparison,
    mapped: dict[str, _MappedAction | None],
    action_matches: dict[str, _ActionMatch],
    rows: dict[str, ChangeProvenance],
    diagnostics: tuple[ProvenanceDiagnostic, ...],
    source_reviews: list[DocumentComment],
    action_reviews: list[tuple[str, DocumentComment]],
) -> dict[str, str]:
    candidates: dict[str, list[tuple[str, DocumentComment]]] = defaultdict(list)
    for action_id, action_map in mapped.items():
        if action_map is None:
            continue
        action = action_map.target.action
        payload = format_action_comment(action)
        if not payload:
            continue
        match = action_matches.get(action_id)
        expected_span = match.output_span if match is not None else None
        if expected_span is None and (
            action.action_type not in WRITING_ACTIONS or not _is_trackable(action)
        ):
            expected_span = (action_map.start, action_map.end)
        for event in comparison.comment_changes:
            comment = event.right
            if comment is None or comment.text != payload:
                continue
            anchor = comment.anchor
            if (
                anchor is None
                or anchor.locator != action_map.target.locator
                or anchor.pair_id != action_map.pair_id
                or anchor.block_id != action_map.right_block.id
                or anchor.start_offset is None
                or anchor.end_offset is None
            ):
                continue
            if expected_span is None or not _contains(
                expected_span, (anchor.start_offset, anchor.end_offset)
            ):
                continue
            if _blocked_by_diagnostic(
                diagnostics,
                action_map.target.locator,
                "comment",
                pair_id=action_map.pair_id,
            ):
                continue
            # A retained source comment is recognized before actions and cannot be
            # reclassified by its author, Word ID, or coincidentally matching body.
            if event.change_id in rows and rows[event.change_id].status is ProvenanceStatus.SOURCE:
                continue
            candidates[event.change_id].append((action_id, comment))

    action_events: dict[str, set[str]] = defaultdict(set)
    for change_id, matches in candidates.items():
        for action_id, _comment in matches:
            action_events[action_id].add(change_id)

    result: dict[str, str] = {}
    for change_id, matches in candidates.items():
        unique = {(action_id, _comment_identity(comment)) for action_id, comment in matches}
        action_ids = {action_id for action_id, _key in unique}
        comments = {_key for _action_id, _key in unique}
        if len(action_ids) != 1 or len(comments) != 1:
            continue
        action_id = next(iter(action_ids))
        if len(action_events[action_id]) != 1:
            continue
        event = next(event for event in comparison.comment_changes if event.change_id == change_id)
        assert event.right is not None
        rows[change_id] = ChangeProvenance(
            change_id,
            "comment",
            ProvenanceStatus.VERIFIED_ACTION,
            (action_id,),
            ("hash_chain_verified", "shared_comment_formatter_matched", "comment_anchor_matched"),
        )
        result[change_id] = action_id
        action_reviews.append((action_id, event.right))
    return result


def _mark_source_comments_direct(
    comparison: DocxDocumentComparison,
    rows: dict[str, ChangeProvenance],
    source_reviews: list[DocumentComment],
) -> None:
    # Source comments are identified by exact body, physical paragraph locator,
    # and root/reply role when matching across files. Any left comment belongs to
    # the exact, hash-bound source artifact, so a changed comment event must not be
    # relabelled as action-generated. Author and Word comment ID are excluded.
    for event in comparison.comment_changes:
        comment = event.left
        if comment is None or comment.anchor is None or comment.anchor.locator is None:
            continue
        right = event.right
        rows[event.change_id] = ChangeProvenance(
            event.change_id,
            "comment",
            ProvenanceStatus.SOURCE,
            evidence_codes=("source_comment_present_in_input",),
        )
        if right is not None and _comment_identity(comment) == _comment_identity(right):
            source_reviews.append(right)


def _reference_key(reference: RevisionReference) -> tuple[object, ...]:
    return (
        reference.part_name,
        reference.locator,
        reference.kind,
        reference.revision_id,
        reference.container_id,
        reference.text,
        reference.start_offset,
        reference.end_offset,
    )


def _comment_identity(comment: DocumentComment) -> tuple[object, ...]:
    anchor = comment.anchor
    return (
        comment.text,
        anchor.locator if anchor is not None else None,
        bool(comment.parent_id),
    )


def _unique_comments(comments: Sequence[DocumentComment]) -> tuple[DocumentComment, ...]:
    counts = Counter(_comment_identity(item) for item in comments)
    return tuple(item for item in comments if counts[_comment_identity(item)] == 1)


def _is_trackable(action: ReviewAction) -> bool:
    return (
        action.status is not ActionStatus.CONFLICT
        and action.metadata.get("blocked_from_corrected") is not True
        and action.action_type in WRITING_ACTIONS
    )


def _is_deletion(action: ReviewAction) -> bool:
    return action.action_type in _DELETE_ACTIONS or (
        action.action_type in _REPLACE_ACTIONS and not action.replacement_text
    )


def _can_accept(action: ReviewAction) -> bool:
    return (
        _is_trackable(action)
        and action.status is ActionStatus.APPLIED
        and action.apply_to_corrected is True
    )


def _contains(outer: tuple[int, int], inner: tuple[int, int]) -> bool:
    return outer[0] <= inner[0] <= inner[1] <= outer[1]

"""Minimal DOCX renderers for reviewed and corrected output."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from docx import Document as DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from reviewkit.actions import actions_for_paragraph, apply_corrections_to_text
from reviewkit.document import ReviewDocument
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType

_SegmentKind = Literal["text", "ins", "del"]


@dataclass(frozen=True)
class _ReviewerIdentity:
    """Author identity stamped onto tracked-change revisions and Word comments."""

    author: str = "Reviewer"
    initials: str = "RV"


@dataclass
class _Segment:
    kind: _SegmentKind
    text: str
    rpr: Any | None = None
    action_id: str | None = None
    revision_id: int | None = None
    start_comments: list[int] = field(default_factory=list)
    end_comments: list[int] = field(default_factory=list)


def render_reviewed_docx(
    document: ReviewDocument,
    actions: list[ReviewAction],
    output_path: str | Path,
    *,
    comment_author: str = "Reviewer",
    comment_initials: str = "RV",
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    docx = DocxDocument(str(document.source_path)) if document.source_path else DocxDocument()
    reviewer = _ReviewerIdentity(author=comment_author, initials=comment_initials)
    revision_id = 1

    for section in document.sections:
        for paragraph in section.paragraphs:
            paragraph_actions = actions_for_paragraph(document, paragraph, actions)
            docx_paragraph = _paragraph_for_locator(docx, paragraph.locator)
            if docx_paragraph is None:
                docx_paragraph = docx.add_paragraph(paragraph.text)
            revision_id = _add_reviewed_runs(
                docx,
                docx_paragraph,
                paragraph_actions,
                revision_id,
                reviewer,
            )

        section_comments = [
            _comment_text(action)
            for action in actions
            if action.node_id == section.id and not action.original_text
        ]
        for comment in section_comments:
            if comment:
                target = section.locator or (
                    section.paragraphs[0].locator if section.paragraphs else None
                )
                section_paragraph = _paragraph_for_locator(docx, target)
                if section_paragraph is None:
                    section_paragraph = docx.add_paragraph(section.title or section.id)
                if not _add_comment(docx, section_paragraph, comment, reviewer):
                    docx.add_paragraph(comment)

    document_comments = [
        _comment_text(action)
        for action in actions
        if action.node_id == document.id and not action.original_text
    ]
    if document_comments:
        first_paragraph = next(document.iter_paragraphs(), None)
        for comment in document_comments:
            if comment:
                document_paragraph = _paragraph_for_locator(
                    docx,
                    first_paragraph.locator if first_paragraph else None,
                )
                if document_paragraph is None:
                    document_paragraph = docx.add_paragraph("Document-level review")
                if not _add_comment(docx, document_paragraph, comment, reviewer):
                    docx.add_paragraph(comment)

    docx.save(str(path))
    return path


def render_corrected_docx(
    document: ReviewDocument,
    actions: list[ReviewAction],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    docx = DocxDocument()

    for section in document.sections:
        if section.title:
            docx.add_heading(section.title, level=1)
        for paragraph in section.paragraphs:
            paragraph_actions = actions_for_paragraph(document, paragraph, actions)
            corrected = apply_corrections_to_text(paragraph.text, paragraph_actions)
            docx.add_paragraph(corrected)

    docx.save(str(path))
    return path


def _paragraph_for_locator(docx: Any, locator: str | None) -> Any | None:
    if not locator:
        return None

    parts = locator.split(":")
    try:
        if parts[:2] == ["body", "p"]:
            return docx.paragraphs[int(parts[2])]
        if parts[:1] == ["table"]:
            table = docx.tables[int(parts[1])]
            row = table.rows[int(parts[3])]
            cell = row.cells[int(parts[5])]
            return cell.paragraphs[int(parts[7])]
        if parts[:1] == ["header"]:
            return docx.sections[int(parts[1])].header.paragraphs[int(parts[3])]
        if parts[:1] == ["footer"]:
            return docx.sections[int(parts[1])].footer.paragraphs[int(parts[3])]
    except (IndexError, ValueError):
        return None
    return None


def _is_trackable_edit(action: ReviewAction) -> bool:
    if action.status == ActionStatus.CONFLICT:
        return False
    if action.metadata.get("blocked_from_corrected") is True:
        return False
    return action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.DELETE_TEXT,
        ReviewActionType.INSERT_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.DELETE,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }


def _add_reviewed_runs(
    docx: Any,
    paragraph: Any,
    actions: list[ReviewAction],
    revision_id: int,
    reviewer: _ReviewerIdentity,
) -> int:
    if not actions:
        return revision_id

    segments = _paragraph_segments(paragraph)
    for action in _trackable_actions_in_application_order(actions):
        segments, revision_id = _track_action(segments, action, revision_id)

    for action in actions:
        if not _comment_text(action):
            continue
        if _is_trackable_edit(action) and _mark_action_segments(docx, segments, action, reviewer):
            continue
        if action.original_text and _mark_text_comment(
            docx, segments, action.original_text, action, reviewer
        ):
            continue
        _mark_whole_paragraph_comment(docx, segments, action, reviewer)

    _replace_paragraph_children(paragraph, segments, reviewer)
    return revision_id


def _trackable_actions_in_application_order(actions: list[ReviewAction]) -> list[ReviewAction]:
    locator_actions: list[tuple[int, int, int, ReviewAction]] = []
    other_actions: list[ReviewAction] = []
    for index, action in enumerate(actions):
        if not _is_trackable_edit(action):
            continue
        action_range = _locator_action_range(action)
        if action_range is None:
            other_actions.append(action)
            continue
        start, end = action_range
        locator_actions.append((start, end, index, action))
    locator_actions.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in locator_actions] + other_actions


def _track_action(
    segments: list[_Segment],
    action: ReviewAction,
    revision_id: int,
) -> tuple[list[_Segment], int]:
    if action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.DELETE_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.DELETE,
    }:
        action_range = _action_range(segments, action)
        if action_range is None:
            return segments, revision_id
        start, end = action_range
        deleted = _visible_slice(segments, start, end, "del", action.id)
        replacement: list[_Segment] = deleted
        if action.action_type in {
            ReviewActionType.REPLACE_TEXT,
            ReviewActionType.REPLACE,
        } and action.replacement_text:
            replacement.append(
                _Segment("ins", action.replacement_text, _rpr_at(segments, start), action.id)
            )
        revision_id = _assign_revision_ids(replacement, revision_id)
        return _replace_visible_range(segments, start, end, replacement), revision_id

    if action.action_type in {
        ReviewActionType.INSERT_TEXT,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }:
        if action.action_type == ReviewActionType.INSERT_TEXT and action.locator:
            offset = action.locator.char_start or 0
        elif action.original_text:
            start = _visible_text(segments).find(action.original_text)
            if start < 0:
                return segments, revision_id
            offset = start
            if action.action_type == ReviewActionType.INSERT_AFTER:
                offset += len(action.original_text)
        else:
            offset = 0 if action.action_type == ReviewActionType.INSERT_BEFORE else _visible_len(
                segments
            )
        insert = _Segment(
            "ins",
            action.replacement_text or "",
            _rpr_at(segments, offset),
            action.id,
            revision_id,
        )
        return _insert_visible(segments, offset, insert), revision_id + 1

    return segments, revision_id


def _paragraph_segments(paragraph: Any) -> list[_Segment]:
    segments: list[_Segment] = []
    for run in paragraph._p.iter(qn("w:r")):
        rpr = run.find(qn("w:rPr"))
        for text in run.iter(qn("w:t")):
            if text.text:
                segments.append(_Segment("text", text.text, deepcopy(rpr)))
    return segments or [_Segment("text", paragraph.text)]


def _replace_visible_range(
    segments: list[_Segment],
    start: int,
    end: int,
    replacement: list[_Segment],
) -> list[_Segment]:
    segments = _split_visible_offset(_split_visible_offset(segments, end), start)
    result: list[_Segment] = []
    inserted = False
    offset = 0
    for segment in segments:
        next_offset = offset + (len(segment.text) if segment.kind == "text" else 0)
        if segment.kind == "text" and start <= offset and next_offset <= end:
            if not inserted:
                result.extend(segment for segment in replacement if segment.text)
                inserted = True
            offset = next_offset
            continue
        result.append(segment)
        offset = next_offset
    if not inserted:
        result.extend(segment for segment in replacement if segment.text)
    return result


def _insert_visible(segments: list[_Segment], offset: int, insert: _Segment) -> list[_Segment]:
    segments = _split_visible_offset(segments, offset)
    index = _index_at_visible_offset(segments, offset)
    return [*segments[:index], insert, *segments[index:]]


def _split_visible_offset(segments: list[_Segment], offset: int) -> list[_Segment]:
    if offset <= 0:
        return segments

    result: list[_Segment] = []
    cursor = 0
    split_done = False
    for segment in segments:
        if segment.kind != "text":
            result.append(segment)
            continue
        next_cursor = cursor + len(segment.text)
        if not split_done and cursor < offset < next_cursor:
            split_at = offset - cursor
            result.append(_copy_segment(segment, segment.text[:split_at]))
            result.append(_copy_segment(segment, segment.text[split_at:]))
            split_done = True
        else:
            result.append(segment)
        cursor = next_cursor
    return result


def _index_at_visible_offset(segments: list[_Segment], offset: int) -> int:
    cursor = 0
    for index, segment in enumerate(segments):
        if segment.kind != "text":
            continue
        if cursor >= offset:
            return index
        cursor += len(segment.text)
        if cursor >= offset:
            return index + 1
    return len(segments)


def _visible_slice(
    segments: list[_Segment],
    start: int,
    end: int,
    kind: Literal["ins", "del"],
    action_id: str,
) -> list[_Segment]:
    segments = _split_visible_offset(_split_visible_offset(segments, end), start)
    selected: list[_Segment] = []
    offset = 0
    for segment in segments:
        next_offset = offset + (len(segment.text) if segment.kind == "text" else 0)
        if segment.kind == "text" and start <= offset and next_offset <= end:
            selected.append(_Segment(kind, segment.text, deepcopy(segment.rpr), action_id))
        offset = next_offset
    return selected


def _assign_revision_ids(segments: list[_Segment], revision_id: int) -> int:
    for segment in segments:
        if segment.kind != "text":
            segment.revision_id = revision_id
            revision_id += 1
    return revision_id


def _visible_text(segments: list[_Segment]) -> str:
    return "".join(segment.text for segment in segments if segment.kind == "text")


def _action_range(segments: list[_Segment], action: ReviewAction) -> tuple[int, int] | None:
    locator_range = _locator_action_range(action)
    if locator_range is not None:
        return locator_range
    if not action.original_text:
        return None
    start = _visible_text(segments).find(action.original_text)
    if start < 0:
        return None
    return start, start + len(action.original_text)


def _locator_action_range(action: ReviewAction) -> tuple[int, int] | None:
    if not action.locator:
        return None
    if action.locator.char_start is None or action.locator.char_end is None:
        return None
    return action.locator.char_start, action.locator.char_end


def _visible_len(segments: list[_Segment]) -> int:
    return len(_visible_text(segments))


def _rpr_at(segments: list[_Segment], offset: int) -> Any | None:
    cursor = 0
    previous: Any | None = None
    for segment in segments:
        if segment.kind != "text":
            continue
        next_cursor = cursor + len(segment.text)
        if cursor <= offset <= next_cursor:
            return deepcopy(segment.rpr)
        previous = segment.rpr
        cursor = next_cursor
    return deepcopy(previous)


def _copy_segment(segment: _Segment, text: str) -> _Segment:
    return _Segment(
        kind=segment.kind,
        text=text,
        rpr=deepcopy(segment.rpr),
        action_id=segment.action_id,
        revision_id=segment.revision_id,
        start_comments=list(segment.start_comments),
        end_comments=list(segment.end_comments),
    )


def _replace_paragraph_children(
    paragraph: Any, segments: list[_Segment], reviewer: _ReviewerIdentity
) -> None:
    parent = paragraph._p
    for child in list(parent):
        if child.tag != qn("w:pPr"):
            parent.remove(child)

    for segment in segments:
        if not segment.text:
            continue
        for comment_id in segment.start_comments:
            parent.append(_comment_range("w:commentRangeStart", comment_id))
        if segment.kind == "text":
            _append_text_run(parent, segment.text, segment.rpr)
        else:
            _append_revision(
                parent, segment.kind, segment.text, reviewer, segment.rpr, segment.revision_id
            )
        for comment_id in reversed(segment.end_comments):
            parent.append(_comment_range("w:commentRangeEnd", comment_id))
            parent.append(_comment_reference_run(comment_id))


def _append_text_run(parent: Any, text: str, rpr: Any | None = None) -> None:
    run = OxmlElement("w:r")
    if rpr is not None:
        run.append(deepcopy(rpr))
    text_element = OxmlElement("w:t")
    _set_text(text_element, text)
    run.append(text_element)
    parent.append(run)


def _append_revision(
    parent: Any,
    kind: Literal["ins", "del"],
    text: str,
    reviewer: _ReviewerIdentity,
    rpr: Any | None = None,
    revision_id: int | None = None,
) -> None:
    revision = OxmlElement(f"w:{kind}")
    revision.set(qn("w:id"), str(revision_id or 0))
    revision.set(qn("w:author"), reviewer.author)
    revision.set(qn("w:date"), datetime.now(UTC).replace(microsecond=0).isoformat())

    run = OxmlElement("w:r")
    if rpr is not None:
        run.append(deepcopy(rpr))
    text_element = OxmlElement("w:t" if kind == "ins" else "w:delText")
    _set_text(text_element, text)
    run.append(text_element)
    revision.append(run)
    parent.append(revision)


def _set_text(element: Any, text: str) -> None:
    if text[:1].isspace() or text[-1:].isspace():
        element.set(qn("xml:space"), "preserve")
    element.text = text


def _mark_action_segments(
    docx: Any, segments: list[_Segment], action: ReviewAction, reviewer: _ReviewerIdentity
) -> bool:
    indexes = [index for index, segment in enumerate(segments) if segment.action_id == action.id]
    return _mark_comment_indexes(docx, segments, indexes, action, reviewer)


def _mark_text_comment(
    docx: Any,
    segments: list[_Segment],
    original_text: str,
    action: ReviewAction,
    reviewer: _ReviewerIdentity,
) -> bool:
    start = _visible_text(segments).find(original_text)
    if start < 0:
        return False
    end = start + len(original_text)
    segments[:] = _split_visible_offset(_split_visible_offset(segments, end), start)
    indexes: list[int] = []
    offset = 0
    for index, segment in enumerate(segments):
        next_offset = offset + (len(segment.text) if segment.kind == "text" else 0)
        if segment.kind == "text" and start <= offset and next_offset <= end:
            indexes.append(index)
        offset = next_offset
    return _mark_comment_indexes(docx, segments, indexes, action, reviewer)


def _mark_whole_paragraph_comment(
    docx: Any, segments: list[_Segment], action: ReviewAction, reviewer: _ReviewerIdentity
) -> bool:
    indexes = [index for index, segment in enumerate(segments) if segment.text]
    return _mark_comment_indexes(docx, segments, indexes, action, reviewer)


def _mark_comment_indexes(
    docx: Any,
    segments: list[_Segment],
    indexes: list[int],
    action: ReviewAction,
    reviewer: _ReviewerIdentity,
) -> bool:
    comment = _comment_text(action)
    if comment is None or not indexes:
        return False
    comment_id = _create_comment(docx, comment, reviewer)
    segments[indexes[0]].start_comments.append(comment_id)
    segments[indexes[-1]].end_comments.append(comment_id)
    return True


def _create_comment(docx: Any, text: str, reviewer: _ReviewerIdentity) -> int:
    comment = docx.comments.add_comment(
        text=text, author=reviewer.author, initials=reviewer.initials
    )
    return int(comment.comment_id)


def _comment_range(tag: str, comment_id: int) -> Any:
    element = OxmlElement(tag)
    element.set(qn("w:id"), str(comment_id))
    return element


def _comment_reference_run(comment_id: int) -> Any:
    run = OxmlElement("w:r")
    reference = OxmlElement("w:commentReference")
    reference.set(qn("w:id"), str(comment_id))
    run.append(reference)
    return run


def _comment_text(action: ReviewAction) -> str | None:
    label = _comment_label(action)
    parts = [f"{label}: {action.comment or action.reason or action.policy_reason or ''}".rstrip()]
    if action.original_text:
        parts.append(f"Original: {action.original_text!r}")
    if action.replacement_text:
        parts.append(f"Replacement: {action.replacement_text!r}")
    if action.category:
        parts.append(f"Category: {action.category}")
    if action.policy_reason:
        parts.append(f"Policy: {action.policy_reason}")
    if action.references:
        refs = ", ".join(reference.label or reference.source for reference in action.references)
        parts.append(f"References: {refs}")
    if action.evidence_refs:
        evidence = ", ".join(
            ref.locator or ref.segment_id or ref.source or "evidence"
            for ref in action.evidence_refs
        )
        parts.append(f"Evidence: {evidence}")
    parts.append(f"Status: {action.status.value}")
    return "\n".join(parts)


def _comment_label(action: ReviewAction) -> str:
    if action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.DELETE_TEXT,
        ReviewActionType.INSERT_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.DELETE,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }:
        if action.status == ActionStatus.APPLIED:
            return "CORRECTION"
        if action.status == ActionStatus.CONFLICT:
            return "CONFLICT"
        if action.status == ActionStatus.NEEDS_HUMAN_DECISION:
            return "HUMAN_DECISION"
        return "SUGGESTION"
    if action.action_type == ReviewActionType.QUESTION:
        return "QUESTION"
    if action.action_type == ReviewActionType.RISK:
        return "RISK"
    if action.action_type == ReviewActionType.SUGGESTION:
        return "SUGGESTION"
    if action.action_type == ReviewActionType.PRAISE:
        return "PRAISE"
    if action.action_type == ReviewActionType.SUMMARY:
        return "SUMMARY"
    return "COMMENT"


def _add_comment(
    docx: Any, paragraph: Any, text: str, reviewer: _ReviewerIdentity
) -> bool:
    try:
        runs = getattr(paragraph, "runs")
        if not runs:
            paragraph.add_run("")
            runs = getattr(paragraph, "runs")
        comment = docx.comments.add_comment(
            text=text, author=reviewer.author, initials=reviewer.initials
        )
        runs[0].mark_comment_range(runs[-1], comment.comment_id)
    except AttributeError:
        return False
    return True

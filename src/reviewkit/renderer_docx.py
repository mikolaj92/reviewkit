"""Review semantics mapped to Docxtor physical review commands."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from docxtor import (
    PhysicalReviewComment,
    PhysicalReviewEdit,
    PhysicalReviewer,
    PhysicalReviewNote,
    PhysicalReviewPlan,
    PhysicalReviewRenderError,
    project_docx_for_review,
    render_physical_clean,
    render_physical_review,
    write_docx_from_paragraphs,
)

from reviewkit.actions import (
    actions_for_paragraph,
    should_apply_to_corrected,
)
from reviewkit.comment_formatter import action_comment_label, format_action_comment
from reviewkit.document import ReviewDocument
from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    RevisionCoverageError,
    RevisionCoverageState,
)
from reviewkit.policy import WRITING_ACTIONS


@dataclass(frozen=True)
class RendererCapabilities:
    """Action and physical-locator shapes a renderer can apply."""

    supported_action_types: frozenset[ReviewActionType]
    supported_locator_prefixes: frozenset[str]


DOCX_RENDERER_CAPABILITIES = RendererCapabilities(
    supported_action_types=frozenset(ReviewActionType),
    supported_locator_prefixes=frozenset({"body", "table", "header", "footer"}),
)


class RenderIntegrityError(RuntimeError):
    pass


_WRITE_REPLACE = {ReviewActionType.REPLACE_TEXT, ReviewActionType.REPLACE}
_WRITE_DELETE = {ReviewActionType.DELETE_TEXT, ReviewActionType.DELETE}
_WRITE_INSERT = {
    ReviewActionType.INSERT_TEXT,
    ReviewActionType.INSERT_BEFORE,
    ReviewActionType.INSERT_AFTER,
}


def render_reviewed_docx(
    document: ReviewDocument,
    actions: list[ReviewAction],
    output_path: str | Path,
    *,
    comment_author: str = "Reviewer",
    comment_initials: str = "RV",
    revision_timestamp: datetime | None = None,
) -> Path:
    source_path = document.source_path
    temporary_source: tempfile.TemporaryDirectory[str] | None = None
    if source_path is None:
        temporary_source = tempfile.TemporaryDirectory()
        source_path = write_docx_from_paragraphs(
            Path(temporary_source.name) / "source.docx",
            tuple(p.text for p in document.iter_paragraphs()),
        )
    if document.revision_ledger.coverage != RevisionCoverageState.COMPLETE:
        raise RevisionCoverageError("source revision coverage is incomplete")
    projection = project_docx_for_review(source_path)
    texts = {p.locator: p.text for p in projection.paragraphs}
    for paragraph in document.iter_paragraphs():
        if paragraph.locator and paragraph.locator not in texts:
            raise RenderIntegrityError(
                f"source paragraph locator {paragraph.locator!r} does not resolve"
            )
    _assert_writing_routes(document, actions)
    revisions = []
    comments = []
    notes = []
    for paragraph_index, paragraph in enumerate(document.iter_paragraphs()):
        locator = paragraph.locator or (
            projection.paragraphs[paragraph_index].locator
            if paragraph_index < len(projection.paragraphs)
            else ""
        )
        raw = texts.get(locator)
        if not locator or raw is None:
            continue
        selected = actions_for_paragraph(document, paragraph, actions)
        consumed: list[tuple[int, int]] = []
        for action in _ordered(raw, selected):
            if _is_trackable(action):
                if action.new_paragraph and not action.replacement_text:
                    raise RenderIntegrityError(f"new paragraph action {action.id!r} has no text")
                resolved = _resolve(raw, action)
                if resolved is None:
                    raise RenderIntegrityError(
                        f"reviewed.docx cannot anchor action {action.id!r} on {action.node_id!r}"
                    )
                else:
                    start, end = resolved
                    if end > start and any(
                        start < used_end and used_start < end for used_start, used_end in consumed
                    ):
                        comments.append(_physical_comment(locator, raw, action))
                        continue
                    if end > start:
                        consumed.append((start, end))
                    kind = (
                        "replace"
                        if action.action_type in _WRITE_REPLACE
                        else "delete"
                        if action.action_type in _WRITE_DELETE
                        else "insert"
                    )
                    revisions.append(
                        PhysicalReviewEdit(
                            action.id,
                            locator,
                            kind,
                            start,
                            end,
                            action.replacement_text or "",
                            raw[start:end] if end > start else None,
                            format_action_comment(action),
                            action.new_paragraph,
                            action.action_type != ReviewActionType.INSERT_BEFORE,
                        )
                    )
            text = format_action_comment(action)
            if text and not _is_trackable(action):
                comments.append(_physical_comment(locator, raw, action))
    # Actions scoped above a paragraph need an explicit review-note anchor when
    # their quote does not occur in the scoped document.
    routed = {
        action.id
        for action in actions
        if any(
            action in actions_for_paragraph(document, paragraph, list(actions))
            for paragraph in document.iter_paragraphs()
        )
    }
    scope_ids = {document.id, *(section.id for section in document.sections)}
    for action in actions:
        comment_text = format_action_comment(action)
        if not comment_text or action.id in routed:
            continue
        if action.node_id in scope_ids and action.original_text:
            notes.append(
                PhysicalReviewNote(
                    f"Unanchored review action — {action_comment_label(action)}", comment_text
                )
            )
        elif action.node_id in scope_ids and projection.paragraphs:
            comments.append(PhysicalReviewComment(projection.paragraphs[0].locator, comment_text))

    date = (
        "1970-01-01T00:00:00+00:00"
        if revision_timestamp is None
        else revision_timestamp.replace(microsecond=0).isoformat()
    )
    try:
        return render_physical_review(
            source_path,
            output_path,
            PhysicalReviewPlan(tuple(revisions), tuple(comments), tuple(notes)),
            reviewer=PhysicalReviewer(comment_author, comment_initials, date),
        )
    except PhysicalReviewRenderError as exc:
        raise RenderIntegrityError(str(exc)) from exc


def render_corrected_docx(
    document: ReviewDocument, actions: list[ReviewAction], output_path: str | Path
) -> Path:
    source_path = document.source_path
    temporary_source: tempfile.TemporaryDirectory[str] | None = None
    if source_path is None:
        temporary_source = tempfile.TemporaryDirectory()
        source_path = write_docx_from_paragraphs(
            Path(temporary_source.name) / "source.docx",
            tuple(p.text for p in document.iter_paragraphs()),
        )
    if document.revision_ledger.coverage != RevisionCoverageState.COMPLETE:
        raise RevisionCoverageError("source revision coverage is incomplete")
    _assert_writing_routes(document, [a for a in actions if should_apply_to_corrected(a)])
    projection = project_docx_for_review(source_path)
    texts = {p.locator: p.text for p in projection.paragraphs}
    for paragraph in document.iter_paragraphs():
        if paragraph.locator and paragraph.locator not in texts:
            raise RenderIntegrityError(
                f"source paragraph locator {paragraph.locator!r} does not resolve"
            )
    edits: list[PhysicalReviewEdit] = []
    for paragraph_index, paragraph in enumerate(document.iter_paragraphs()):
        locator = paragraph.locator or (
            projection.paragraphs[paragraph_index].locator
            if paragraph_index < len(projection.paragraphs)
            else ""
        )
        raw = texts.get(locator)
        if raw is None:
            continue
        selected = [
            action
            for action in actions_for_paragraph(document, paragraph, actions)
            if should_apply_to_corrected(action)
        ]
        consumed: list[tuple[int, int]] = []
        for action in _ordered(raw, selected):
            resolved = _resolve(raw, action)
            if resolved is None:
                raise RenderIntegrityError(f"corrected.docx cannot anchor action {action.id!r}")
            start, end = resolved
            if end > start and any(
                start < used_end and used_start < end for used_start, used_end in consumed
            ):
                raise RenderIntegrityError(
                    f"corrected.docx action {action.id!r} overlaps an earlier applied edit"
                )
            if end > start:
                consumed.append((start, end))
            kind = (
                "replace"
                if action.action_type in _WRITE_REPLACE
                else "delete"
                if action.action_type in _WRITE_DELETE
                else "insert"
            )
            edits.append(
                PhysicalReviewEdit(
                    action.id,
                    locator,
                    kind,
                    start,
                    end,
                    action.replacement_text or "",
                    raw[start:end] if end > start else None,
                )
            )
    try:
        return render_physical_clean(source_path, output_path, tuple(edits))
    except PhysicalReviewRenderError as exc:
        raise RenderIntegrityError(str(exc)) from exc


def _ordered(text: str, actions: list[ReviewAction]) -> list[ReviewAction]:
    del text
    return sorted(actions, key=lambda action: action.status != ActionStatus.APPLIED)


def _locator(action: ReviewAction) -> tuple[int, int] | None:
    if (
        action.locator
        and action.locator.char_start is not None
        and action.locator.char_end is not None
    ):
        if action.action_type == ReviewActionType.INSERT_AFTER:
            return action.locator.char_end, action.locator.char_end
        return action.locator.char_start, action.locator.char_end
    return None


def _physical_comment(locator: str, text: str, action: ReviewAction) -> PhysicalReviewComment:
    resolved = _resolve(text, action)
    start, end = resolved if resolved is not None else (None, None)
    if start is not None and end is not None and not 0 <= start < end <= len(text):
        start, end = None, None
    if start is not None and end is not None:
        quoted = text[start:end]
    else:
        quoted = action.original_text
    return PhysicalReviewComment(
        locator,
        format_action_comment(action),
        start_offset=start,
        end_offset=end,
        anchor_text=quoted,
    )


def _resolve(text: str, action: ReviewAction) -> tuple[int, int] | None:
    loc = _locator(action)
    if loc:
        if loc[1] > len(text):
            return None
        expected = action.locator.original_text if action.locator else None
        expected = expected or action.original_text
        if expected is not None and text[loc[0] : loc[1]] != expected:
            leading = len(text) - len(text.lstrip())
            shifted = (loc[0] + leading, loc[1] + leading)
            if shifted[1] <= len(text) and text[shifted[0] : shifted[1]] == expected:
                return shifted
            if action.action_type not in _WRITE_INSERT:
                return None
        return loc
    if action.original_text:
        start = text.find(action.original_text)
        if start < 0:
            return None
        if action.action_type == ReviewActionType.INSERT_AFTER:
            return start + len(action.original_text), start + len(action.original_text)
        if action.action_type in {ReviewActionType.INSERT_BEFORE, ReviewActionType.INSERT_TEXT}:
            return start, start
        return start, start + len(action.original_text)
    if action.action_type in _WRITE_INSERT:
        return (
            (0, 0)
            if action.action_type == ReviewActionType.INSERT_BEFORE
            else (len(text), len(text))
        )
    return None


def _assert_writing_routes(document: ReviewDocument, actions: list[ReviewAction]) -> None:
    paragraph_ids = {p.id for p in document.iter_paragraphs()}
    sentence_ids = {s.id for s in document.iter_sentences()}
    for action in actions:
        if action.action_type not in WRITING_ACTIONS or not _is_trackable(action):
            continue
        if action.node_id not in paragraph_ids and action.node_id not in sentence_ids:
            raise RenderIntegrityError(
                f"reviewed.docx action {action.id!r} on {action.node_id!r} routes to no paragraph"
            )


def _is_trackable(action: ReviewAction) -> bool:
    return (
        action.status != ActionStatus.CONFLICT
        and action.metadata.get("blocked_from_corrected") is not True
        and action.action_type in WRITING_ACTIONS
    )

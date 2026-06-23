"""Minimal DOCX renderers for reviewed and corrected output."""

from __future__ import annotations

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
_Segment = tuple[_SegmentKind, str]


def render_reviewed_docx(
    document: ReviewDocument,
    actions: list[ReviewAction],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    docx = DocxDocument()
    revision_id = 1

    for section in document.sections:
        if section.title:
            docx.add_heading(section.title, level=1)
        for paragraph in section.paragraphs:
            paragraph_actions = actions_for_paragraph(document, paragraph, actions)
            docx_paragraph = docx.add_paragraph()
            revision_id = _add_reviewed_runs(
                docx_paragraph,
                paragraph.text,
                paragraph_actions,
                revision_id,
            )
            for action in paragraph_actions:
                comment = _comment_text(action)
                if comment and not _add_comment(docx, docx_paragraph, comment):
                    docx.add_paragraph(comment)

        section_comments = [
            _comment_text(action)
            for action in actions
            if action.node_id == section.id and not action.original_text
        ]
        for comment in section_comments:
            if comment:
                section_paragraph = docx.add_paragraph(
                    f"Section review: {section.title or section.id}"
                )
                if not _add_comment(docx, section_paragraph, comment):
                    docx.add_paragraph(comment)

    document_comments = [
        _comment_text(action)
        for action in actions
        if action.node_id == document.id and not action.original_text
    ]
    if document_comments:
        docx.add_heading("Document review", level=1)
        for comment in document_comments:
            if comment:
                document_paragraph = docx.add_paragraph("Document-level review")
                if not _add_comment(docx, document_paragraph, comment):
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


def _add_reviewed_runs(
    paragraph: Any,
    text: str,
    actions: list[ReviewAction],
    revision_id: int,
) -> int:
    for kind, value in _reviewed_segments(text, actions):
        if kind == "text":
            _append_text_run(paragraph._p, value)
            continue
        _append_revision(paragraph._p, kind, value, revision_id)
        revision_id += 1
    return revision_id


def _reviewed_segments(text: str, actions: list[ReviewAction]) -> list[_Segment]:
    segments: list[_Segment] = [("text", text)]
    for action in actions:
        if action.status == ActionStatus.CONFLICT:
            continue
        if action.metadata.get("blocked_from_corrected") is True:
            continue
        if action.action_type == ReviewActionType.REPLACE and action.original_text:
            segments = _replace_once(
                segments,
                action.original_text,
                [
                    ("del", action.original_text),
                    ("ins", action.replacement_text or ""),
                ],
            )
        elif action.action_type == ReviewActionType.DELETE and action.original_text:
            segments = _replace_once(segments, action.original_text, [("del", action.original_text)])
        elif action.action_type == ReviewActionType.INSERT_BEFORE:
            insert: _Segment = ("ins", action.replacement_text or "")
            if action.original_text:
                segments = _replace_once(
                    segments,
                    action.original_text,
                    [insert, ("text", action.original_text)],
                )
            else:
                segments = [insert, *segments]
        elif action.action_type == ReviewActionType.INSERT_AFTER:
            insert = ("ins", action.replacement_text or "")
            if action.original_text:
                segments = _replace_once(
                    segments,
                    action.original_text,
                    [("text", action.original_text), insert],
                )
            else:
                segments = [*segments, insert]
    return [(kind, value) for kind, value in segments if value]


def _replace_once(
    segments: list[_Segment],
    needle: str,
    replacement: list[_Segment],
) -> list[_Segment]:
    if not needle:
        return segments

    for index, (kind, value) in enumerate(segments):
        if kind != "text":
            continue
        before, found, after = value.partition(needle)
        if not found:
            continue

        updated: list[_Segment] = []
        if before:
            updated.append(("text", before))
        updated.extend(segment for segment in replacement if segment[1])
        if after:
            updated.append(("text", after))
        return [*segments[:index], *updated, *segments[index + 1 :]]
    return segments


def _append_text_run(parent: Any, text: str) -> None:
    run = OxmlElement("w:r")
    text_element = OxmlElement("w:t")
    _set_text(text_element, text)
    run.append(text_element)
    parent.append(run)


def _append_revision(parent: Any, kind: Literal["ins", "del"], text: str, revision_id: int) -> None:
    revision = OxmlElement(f"w:{kind}")
    revision.set(qn("w:id"), str(revision_id))
    revision.set(qn("w:author"), "ReviewKit")
    revision.set(qn("w:date"), datetime.now(UTC).replace(microsecond=0).isoformat())

    run = OxmlElement("w:r")
    text_element = OxmlElement("w:t" if kind == "ins" else "w:delText")
    _set_text(text_element, text)
    run.append(text_element)
    revision.append(run)
    parent.append(revision)


def _set_text(element: Any, text: str) -> None:
    if text[:1].isspace() or text[-1:].isspace():
        element.set(qn("xml:space"), "preserve")
    element.text = text


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


def _add_comment(docx: Any, paragraph: Any, text: str) -> bool:
    try:
        runs = getattr(paragraph, "runs")
        if not runs:
            paragraph.add_run("")
            runs = getattr(paragraph, "runs")
        comment = docx.comments.add_comment(text=text, author="ReviewKit", initials="RK")
        runs[0].mark_comment_range(runs[-1], comment.comment_id)
    except AttributeError:
        return False
    return True

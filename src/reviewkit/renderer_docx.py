"""Minimal DOCX renderers for reviewed and corrected output."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document as DocxDocument

from reviewkit.actions import actions_for_paragraph, apply_corrections_to_text
from reviewkit.document import ReviewDocument
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType


def render_reviewed_docx(
    document: ReviewDocument,
    actions: list[ReviewAction],
    output_path: str | Path,
) -> Path:
    # TODO: Replace this marker-based renderer with true Word Track Changes/comments
    # via OpenXML once the low-level implementation is introduced.
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    docx = DocxDocument()

    for section in document.sections:
        if section.title:
            docx.add_heading(section.title, level=1)
        for paragraph in section.paragraphs:
            paragraph_actions = actions_for_paragraph(document, paragraph, actions)
            docx_paragraph = docx.add_paragraph(_reviewed_text(paragraph.text, paragraph_actions))
            for action in paragraph_actions:
                comment = _comment_text(action)
                if comment and not _add_comment(docx, docx_paragraph, comment):
                    marker = _comment_marker(action)
                    if marker:
                        docx.add_paragraph(marker)

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


def _reviewed_text(text: str, actions: list[ReviewAction]) -> str:
    result = text
    for action in actions:
        if action.status == ActionStatus.CONFLICT:
            continue
        if action.metadata.get("blocked_from_corrected") is True:
            continue
        if action.action_type == ReviewActionType.REPLACE and action.original_text:
            result = result.replace(
                action.original_text,
                f"[DELETE: {action.original_text}][INSERT: {action.replacement_text or ''}]",
                1,
            )
        elif action.action_type == ReviewActionType.DELETE and action.original_text:
            result = result.replace(action.original_text, f"[DELETE: {action.original_text}]", 1)
        elif action.action_type == ReviewActionType.INSERT_BEFORE:
            insert = f"[INSERT: {action.replacement_text or ''}]"
            if action.original_text:
                result = result.replace(action.original_text, f"{insert}{action.original_text}", 1)
            else:
                result = f"{insert}{result}"
        elif action.action_type == ReviewActionType.INSERT_AFTER:
            insert = f"[INSERT: {action.replacement_text or ''}]"
            if action.original_text:
                result = result.replace(action.original_text, f"{action.original_text}{insert}", 1)
            else:
                result = f"{result}{insert}"
    return result


def _comment_marker(action: ReviewAction) -> str | None:
    comment = _comment_text(action)
    if comment is None:
        return None
    label = _comment_label(action)
    return f"[{label}: {comment}]"


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

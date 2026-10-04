"""Side effects on the live DOCX: comment add/update/delete and text change."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from docxtor import (
    PhysicalReviewComment,
    PhysicalReviewEdit,
    PhysicalReviewer,
    PhysicalReviewPlan,
    SurfaceCapability,
    SurfaceKind,
    SurfaceReplacement,
    apply_surface_replacements,
    inventory_docx,
    publish_docx,
    remove_comments,
    render_physical_review,
)

from reviewkit.parser_docx import load_docx
from reviewkit.poziom import Poziom
from reviewkit.visit import Effect, EffectKind, Unit

_DEFAULT_AUTHOR = "Reviewer"
_DEFAULT_INITIALS = "RV"


class DocxEffectError(RuntimeError):
    """A side effect could not be applied to the live DOCX."""


def apply_effect(
    path: Path,
    unit: Unit,
    effect: Effect,
    *,
    author: str = _DEFAULT_AUTHOR,
    initials: str = _DEFAULT_INITIALS,
) -> None:
    """Mutate ``path`` in place. The next visit reads this same file."""
    writer = PhysicalReviewer(
        effect.author or author,
        effect.initials or initials,
        "1970-01-01T00:00:00+00:00",
    )
    if effect.kind is EffectKind.ADD_COMMENT:
        _add_comment(path, unit, effect, writer)
        return
    if effect.kind is EffectKind.UPDATE_COMMENT:
        _update_comment(path, effect)
        return
    if effect.kind is EffectKind.DELETE_COMMENT:
        _delete_comment(path, effect)
        return
    if effect.kind is EffectKind.CHANGE_TEXT:
        _change_text(path, unit, effect, writer)
        return
    raise DocxEffectError(f"unknown effect {effect.kind}")


def _add_comment(path: Path, unit: Unit, effect: Effect, writer: PhysicalReviewer) -> None:
    text = (effect.comment or "").strip()
    if not text:
        raise DocxEffectError("add_comment requires comment text")
    locator = unit.locator
    if not locator:
        raise DocxEffectError("add_comment requires a paragraph locator")
    start, end = unit.char_start, unit.char_end
    expected = None
    if start is not None and end is not None and 0 <= start < end <= len(unit.text):
        expected = unit.text[start:end]
    elif unit.text:
        start, end, expected = 0, len(unit.text), unit.text
    comment = PhysicalReviewComment(locator, text, start, end, expected)
    render_physical_review(path, path, PhysicalReviewPlan(comments=(comment,)), reviewer=writer)


def _update_comment(path: Path, effect: Effect) -> None:
    comment_id = effect.comment_id
    text = effect.comment
    if not comment_id or text is None:
        raise DocxEffectError("update_comment requires comment_id and comment text")
    before = path.read_bytes()
    inventory = inventory_docx(before)
    prefix = _comment_element_prefix(inventory, comment_id)
    bodies = [
        surface
        for surface in inventory.surfaces
        if surface.kind is SurfaceKind.TEXT
        and surface.part_name == "word/comments.xml"
        and surface.surface_id.startswith(prefix + "/")
        and surface.capability is SurfaceCapability.VALUE_REPLACE
    ]
    if len(bodies) != 1:
        raise DocxEffectError(f"comment {comment_id!r} does not resolve to one replaceable body")
    body = bodies[0]
    result = apply_surface_replacements(
        before,
        [SurfaceReplacement(body.surface_id, text, body.value_sha256)],
    )
    publish_docx(result.data, path, source=before)


def _delete_comment(path: Path, effect: Effect) -> None:
    comment_id = effect.comment_id
    if not comment_id:
        raise DocxEffectError("delete_comment requires comment_id")
    before = path.read_bytes()
    result = remove_comments(before, {comment_id})
    publish_docx(result.data, path, source=before)


def _change_text(path: Path, unit: Unit, effect: Effect, writer: PhysicalReviewer) -> None:
    original = effect.original_text
    replacement = effect.replacement_text
    if original is None or replacement is None:
        raise DocxEffectError("change_text requires original_text and replacement_text")
    document = load_docx(path)
    matches: list[tuple[str, int]] = []
    for paragraph in document.iter_paragraphs():
        if not _paragraph_in_unit(unit, paragraph.locator, paragraph.section_id):
            continue
        haystack = paragraph.text
        if (
            unit.poziom is Poziom.ZDANIE
            and unit.char_start is not None
            and unit.char_end is not None
        ):
            haystack = paragraph.text[unit.char_start : unit.char_end]
        start = haystack.find(original)
        if start < 0:
            continue
        if haystack.find(original, start + 1) >= 0:
            raise DocxEffectError("change_text original_text is not unique on this unit")
        offset = start if unit.poziom is not Poziom.ZDANIE else (unit.char_start or 0) + start
        if not paragraph.locator:
            raise DocxEffectError("change_text requires a paragraph locator")
        matches.append((paragraph.locator, offset))
    if len(matches) != 1:
        raise DocxEffectError("change_text original_text is not unique on this unit")
    locator, start = matches[0]
    end = start + len(original)
    edit = PhysicalReviewEdit(
        sha256(f"{unit.key}:{original}:{replacement}".encode()).hexdigest()[:12],
        locator,
        "replace",
        start,
        end,
        replacement,
        original,
    )
    render_physical_review(path, path, PhysicalReviewPlan(edits=(edit,)), reviewer=writer)


def _paragraph_in_unit(unit: Unit, locator: str | None, section_id: str) -> bool:
    if unit.poziom is Poziom.CALOSC:
        return locator is not None and locator.startswith("body:")
    if unit.poziom is Poziom.ROZDZIAL:
        return section_id == unit.node_id
    return locator is not None and locator == unit.locator


def _comment_element_prefix(inventory: object, comment_id: str) -> str:
    matches = [
        surface.surface_id
        for surface in getattr(inventory, "surfaces", ())
        if getattr(surface, "part_name", None) == "word/comments.xml"
        and getattr(surface, "value", None) == comment_id
        and str(getattr(surface, "surface_id", "")).endswith("id")
    ]
    if len(matches) != 1:
        raise DocxEffectError(f"comment {comment_id!r} is not uniquely addressable")
    surface_id = matches[0]
    prefix, marker, _rest = surface_id.partition(":attr:")
    if marker:
        return prefix
    raise DocxEffectError(f"comment {comment_id!r} has no element prefix")


__all__ = ["DocxEffectError", "apply_effect"]

"""Provider- and domain-blind outcomes for a rendered DOCX review."""

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from collections.abc import Sequence
from docxtor import (
    DocxFactsSnapshot,
    ParagraphFact,
    docx_facts,
    inventory_review_markup,
    read_core_keywords,
    remove_core_keyword_values,
    set_core_keywords,
)
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType, SourceRevisionKind
from reviewkit.parser_docx import load_docx
from reviewkit.policy import WRITING_ACTIONS


@dataclass(frozen=True)
class IncorporatedCommentOutcome:
    comment_id: str
    text: str
    revision_kinds: tuple[str, ...] = ()
    locator: str | None = None


@dataclass(frozen=True)
class ReviewChangeMetrics:
    before_paragraphs: int
    after_paragraphs: int
    before_text_chars: int
    after_text_chars: int
    before_tables: int
    after_tables: int
    before_text_sha256: str
    after_text_sha256: str
    before_structure_sha256: str
    after_structure_sha256: str


@dataclass(frozen=True)
class RenderedActionAssessment:
    matches: bool
    rendered_revision_count: int
    source_revision_hashes: tuple[str, ...]
    unmatched_expected: int = 0
    unmatched_rendered: int = 0


def incorporated_comment_outcomes(
    source: str | Path | bytes,
) -> tuple[IncorporatedCommentOutcome, ...]:
    data = _bytes(source)
    inventory = inventory_review_markup(data)
    fatal = tuple(
        item
        for item in inventory.diagnostics
        if item.code in {"package_unreadable", "comments_unreadable"}
    )
    if fatal:
        detail = "; ".join(item.message for item in fatal)
        raise ValueError(f"review markup coverage is incomplete: {detail}")
    comments = {item.comment_id: item for item in inventory.comments}
    return tuple(
        IncorporatedCommentOutcome(
            item.comment_id,
            comments[item.comment_id].text,
            item.revision_kinds,
            item.locator,
        )
        for item in inventory.comment_revision_associations
        if item.comment_id in comments and comments[item.comment_id].text
    )


def revision_signatures(source: str | Path) -> tuple[str, ...]:
    return tuple(sorted(_revision_hash(*item) for item in _rendered_revisions(source)))


def assess_rendered_actions(
    source: str | Path,
    actions: Sequence[ReviewAction],
    *,
    ignored_revision_hashes: Sequence[str] = (),
) -> RenderedActionAssessment:
    revisions = _rendered_revisions(source)
    source_hashes = tuple(sorted(_revision_hash(*item) for item in revisions))
    ignored = list(ignored_revision_hashes)
    rendered: list[tuple[str, str, str | None]] = []
    for revision in revisions:
        signature = _revision_hash(*revision)
        if signature in ignored:
            ignored.remove(signature)
        else:
            rendered.append(revision)
    expected = _expected_revisions(actions)
    missing = 0
    for item in expected:
        match = next(
            (
                index
                for index, actual in enumerate(rendered)
                if actual[0] == item[0]
                and actual[1] == item[1]
                and (item[2] is None or actual[2] == item[2])
            ),
            None,
        )
        if match is None:
            missing += 1
        else:
            rendered.pop(match)
    return RenderedActionAssessment(
        matches=not ignored and missing == 0 and not rendered,
        rendered_revision_count=len(revisions) - len(ignored_revision_hashes),
        source_revision_hashes=source_hashes,
        unmatched_expected=missing + len(ignored),
        unmatched_rendered=len(rendered),
    )


def measure_review_changes(before: str | Path, after: str | Path) -> ReviewChangeMetrics:
    left = docx_facts(before)
    right = docx_facts(after)
    return ReviewChangeMetrics(
        len(left.paragraphs),
        len(right.paragraphs),
        sum(len(item.text) for item in left.paragraphs),
        sum(len(item.text) for item in right.paragraphs),
        len(left.structure.table_ids),
        len(right.structure.table_ids),
        _text_hash(left.paragraphs),
        _text_hash(right.paragraphs),
        _structure_hash(left),
        _structure_hash(right),
    )


def read_metadata_marker(source: str | Path | bytes, *, prefix: str) -> str | None:
    matches = [
        value[len(prefix) :]
        for value in read_core_keywords(_bytes(source)).split(";")
        if value.startswith(prefix)
    ]
    return matches[0] if len(matches) == 1 else None


def set_metadata_marker(source: str | Path | bytes, *, prefix: str, value: str) -> bytes:
    data = _bytes(source)
    existing = [
        item for item in read_core_keywords(data).split(";") if item and not item.startswith(prefix)
    ]
    existing.append(f"{prefix}{value}")
    return set_core_keywords(data, ";".join(existing))


def strip_metadata_marker(source: str | Path | bytes, *, prefix: str) -> bytes:
    return remove_core_keyword_values(_bytes(source), prefix=prefix)


def _rendered_revisions(source: str | Path) -> list[tuple[str, str, str | None]]:
    inventory = inventory_review_markup(_bytes(source))
    supported = {
        "ins",
        "del",
        "pPrChange",
        "rPrChange",
        "customXmlInsRangeStart",
        "customXmlInsRangeEnd",
        "customXmlDelRangeStart",
        "customXmlDelRangeEnd",
    }
    unsupported = {item.raw_kind for item in inventory.revisions} - supported
    if unsupported:
        raise ValueError(
            "rendered DOCX contains unsupported revision markup: " + ", ".join(sorted(unsupported))
        )
    document = load_docx(source)
    return [
        (
            "ins" if entry.kind is SourceRevisionKind.INSERTED else "del",
            entry.text,
            entry.locator,
        )
        for entry in document.revision_ledger.entries
    ]


def _expected_revisions(actions: Sequence[ReviewAction]) -> list[tuple[str, str, str | None]]:
    result: list[tuple[str, str, str | None]] = []
    for action in actions:
        if (
            action.status is not ActionStatus.APPLIED
            or action.apply_to_corrected is not True
            or action.action_type not in WRITING_ACTIONS
        ):
            continue
        original = (
            action.locator.original_text if action.locator else None
        ) or action.original_text
        replacement = action.replacement_text
        locator = action.node_id if action.node_id.startswith("body:p:") else None
        if action.action_type in {
            ReviewActionType.INSERT_AFTER,
            ReviewActionType.INSERT_BEFORE,
            ReviewActionType.INSERT_TEXT,
        }:
            if replacement:
                result.append(("ins", replacement, locator))
        elif action.action_type in {ReviewActionType.DELETE, ReviewActionType.DELETE_TEXT}:
            if original:
                result.append(("del", original, locator))
        elif original and replacement:
            result.extend((("del", original, locator), ("ins", replacement, locator)))
    return result


def _revision_hash(kind: str, text: str, locator: str | None) -> str:
    payload = f"{kind}\0{locator or ''}\0{text}".encode()
    return sha256(payload).hexdigest()


def _text_hash(paragraphs: Sequence[ParagraphFact]) -> str:
    payload = "".join(f"{len(item.text)}:{item.text}" for item in paragraphs)
    return sha256(payload.encode()).hexdigest()


def _structure_hash(snapshot: DocxFactsSnapshot) -> str:
    payload = "|".join(
        f"{surface.part_name}:{surface.xml_path}:{surface.element_qname}"
        for surface in snapshot.surfaces
        if surface.part_name == "word/document.xml"
    )
    return sha256(payload.encode()).hexdigest()


def _bytes(source: str | Path | bytes) -> bytes:
    return source if isinstance(source, bytes) else Path(source).read_bytes()

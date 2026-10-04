"""Review one DOCX by walking that same file.

The walk is the review. Side effects (add, update, or delete a comment, or
change the text) publish onto the file under review. There is no abstract
copy that is judged first and written out only at the end.

Order: every zdanie, then every akapit, then every rozdział, then the
całość n times. At each unit the host stays or goes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from reviewkit.docx_live import DocxReviewError, LiveDocx
from reviewkit.docx_reviewer import (
    AddComment,
    ChangeText,
    DeleteComment,
    DocxReviewer,
    ReviewDecision,
    SideEffect,
    UpdateComment,
)
from reviewkit.docx_units import Jednostka, list_units, with_visit
from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewResult,
    ReviewStats,
)
from reviewkit.parser_docx import load_docx
from reviewkit.poziom import WALK_ORDER, Poziom, scope_for
from reviewkit.stay_or_go import Ruch, StayOrGoError, stay_or_go


@dataclass(frozen=True)
class WalkEvent:
    """One stay-or-go decision, with side effects that already landed."""

    poziom: Poziom
    node_id: str
    visit: int
    document_pass: int
    ruch: Ruch
    effects: tuple[str, ...]
    comment_texts: tuple[str, ...]
    file_text: str


def review_one_docx(
    path: str | Path,
    reviewer: DocxReviewer,
    *,
    document_passes: int = 1,
    max_visits: int = 32,
    comment_author: str = "Reviewer",
    comment_initials: str = "RV",
) -> ReviewResult:
    """Walk ``path`` in place. ``document_passes`` is n for całość."""
    target = Path(path)
    if document_passes < 1:
        raise DocxReviewError("całość must be walked at least once")
    live = LiveDocx(target, author=comment_author, initials=comment_initials)
    events: list[WalkEvent] = []
    actions: list[ReviewAction] = []

    def record(unit: Jednostka, decision: ReviewDecision) -> None:
        landed = tuple(_kind(effect) for effect in decision.effects)
        document = load_docx(target)
        events.append(
            WalkEvent(
                unit.poziom,
                unit.node_id,
                unit.visit,
                unit.document_pass,
                decision.ruch,
                landed,
                tuple(comment.text for comment in live.comments()),
                document.text,
            )
        )

    for poziom in WALK_ORDER:
        if poziom is Poziom.CALOSC:
            for document_pass in range(1, document_passes + 1):
                _walk_level(
                    live,
                    poziom,
                    reviewer,
                    record,
                    actions,
                    document_pass=document_pass,
                    max_visits=max_visits,
                )
            continue
        _walk_level(
            live,
            poziom,
            reviewer,
            record,
            actions,
            document_pass=0,
            max_visits=max_visits,
        )

    document = load_docx(target)
    return ReviewResult(
        document=document,
        actions=actions,
        reviewed_docx=target,
        stats=ReviewStats.from_actions(actions),
        artifacts={"reviewed_docx": str(target)},
        metrics={"walk": [_event_payload(event) for event in events]},
    )


def _walk_level(
    live: LiveDocx,
    poziom: Poziom,
    reviewer: DocxReviewer,
    record: Callable[[Jednostka, ReviewDecision], None],
    actions: list[ReviewAction],
    *,
    document_pass: int,
    max_visits: int,
) -> None:
    index = 0
    while True:
        units = list_units(load_docx(live.path), poziom, path=live.path)
        if index >= len(units):
            return
        identity = units[index].node_id

        def consider(visit: int, *, _identity: str = identity) -> tuple[Jednostka, ReviewDecision]:
            current_units = list_units(load_docx(live.path), poziom, path=live.path)
            current = next((item for item in current_units if item.node_id == _identity), None)
            if current is None:
                raise DocxReviewError(f"{poziom} {_identity!r} disappeared during the walk")
            unit = with_visit(current, visit, document_pass)
            decision = reviewer.consider(unit)
            for effect in decision.effects:
                _apply(live, unit, effect, actions)
            return unit, decision

        try:
            for unit, decision in stay_or_go(
                consider,
                is_go=lambda item: item[1].ruch == Ruch.GO,
                max_visits=max_visits,
            ):
                record(unit, decision)
        except StayOrGoError as exc:
            raise DocxReviewError(str(exc)) from exc
        index += 1


def _apply(
    live: LiveDocx,
    unit: Jednostka,
    effect: SideEffect,
    actions: list[ReviewAction],
) -> None:
    if isinstance(effect, AddComment):
        locator, start, end, expected = _range(unit, effect.start_offset, effect.end_offset)
        comment_id = live.add_comment(locator, start, end, effect.text, expected_text=expected)
        actions.append(
            _action(
                unit,
                ReviewActionType.COMMENT,
                comment=effect.text,
                metadata={"comment_id": comment_id},
            )
        )
        return
    if isinstance(effect, UpdateComment):
        live.update_comment(effect.comment_id, effect.text)
        actions.append(
            _action(
                unit,
                ReviewActionType.COMMENT,
                comment=effect.text,
                metadata={"comment_id": effect.comment_id, "effect": "update_comment"},
            )
        )
        return
    if isinstance(effect, DeleteComment):
        live.delete_comment(effect.comment_id)
        actions.append(
            _action(
                unit,
                ReviewActionType.COMMENT,
                metadata={"comment_id": effect.comment_id, "effect": "delete_comment"},
            )
        )
        return
    if not isinstance(effect, ChangeText):
        raise DocxReviewError(f"unsupported side effect {type(effect).__name__}")
    locator, start, end, expected = _locate_text(unit, effect.original)
    live.change_text(locator, start, end, effect.replacement)
    actions.append(
        _action(
            unit,
            ReviewActionType.REPLACE_TEXT,
            original=expected,
            replacement=effect.replacement,
        )
    )


def _range(
    unit: Jednostka,
    start_offset: int | None,
    end_offset: int | None,
) -> tuple[str, int, int, str]:
    locator = unit.locator
    if not locator:
        raise DocxReviewError(f"{unit.poziom} {unit.node_id!r} has no paragraph locator")
    start = unit.char_start if start_offset is None else start_offset
    end = unit.char_end if end_offset is None else end_offset
    if not 0 <= start < end:
        raise DocxReviewError(f"empty comment range on {unit.node_id!r}")
    expected = unit.text if start == unit.char_start and end == unit.char_end else None
    if expected is None:
        document = load_docx(unit.path)
        paragraph = next(
            (item for item in document.iter_paragraphs() if item.locator == locator),
            None,
        )
        expected = paragraph.text[start:end] if paragraph is not None else unit.text
    return locator, start, end, expected


def _locate_text(unit: Jednostka, original: str) -> tuple[str, int, int, str]:
    locator = unit.locator
    if not locator:
        raise DocxReviewError(f"{unit.poziom} {unit.node_id!r} has no paragraph locator")
    document = load_docx(unit.path)
    paragraph = next((item for item in document.iter_paragraphs() if item.locator == locator), None)
    if paragraph is None:
        raise DocxReviewError(f"locator {locator!r} does not resolve")
    haystack = paragraph.text
    start = haystack.find(original)
    if start < 0 or haystack.find(original, start + 1) >= 0:
        raise DocxReviewError(f"text {original!r} is not unique on {locator}")
    return locator, start, start + len(original), original


def _kind(effect: SideEffect) -> str:
    if isinstance(effect, AddComment):
        return "add_comment"
    if isinstance(effect, UpdateComment):
        return "update_comment"
    if isinstance(effect, DeleteComment):
        return "delete_comment"
    if isinstance(effect, ChangeText):
        return "change_text"
    raise DocxReviewError(f"unsupported side effect {type(effect).__name__}")


def _action(
    unit: Jednostka,
    action_type: ReviewActionType,
    *,
    comment: str | None = None,
    original: str | None = None,
    replacement: str | None = None,
    metadata: dict[str, str] | None = None,
) -> ReviewAction:
    return ReviewAction(
        scope=scope_for(unit.poziom),
        action_type=action_type,
        node_id=unit.node_id,
        original_text=original,
        replacement_text=replacement,
        comment=comment,
        status=ActionStatus.APPLIED,
        metadata=metadata or {},
    )


def _event_payload(event: WalkEvent) -> dict[str, object]:
    return {
        "poziom": event.poziom.value,
        "node_id": event.node_id,
        "visit": event.visit,
        "document_pass": event.document_pass,
        "ruch": event.ruch.value,
        "effects": list(event.effects),
        "comment_texts": list(event.comment_texts),
        "file_text": event.file_text,
    }


__all__ = ["DocxReviewError", "WalkEvent", "review_one_docx"]

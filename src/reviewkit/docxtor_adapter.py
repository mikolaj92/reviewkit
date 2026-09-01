"""Neutral mapping from prepared ReviewKit actions to Docxtor review operations.

ReviewKit decides *what* an effective action means. Docxtor alone performs the
physical DOCX mutation and returns the mechanical receipts asserted here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from docxtor import (
    DocumentError,
    OperationReceipt,
    OperationStatus,
    ReviewBatchReceipt,
    ReviewTransactionError,
    ReviewCommand,
    RevisionAuthor,
    RevisionPosition,
    RevisionRange,
    apply_review_batch,
    delete_revision,
    insert_revision,
    replace_revision,
)

from reviewkit.document import ReviewDocument
from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType
from reviewkit.policy import WRITING_ACTIONS


class DocxtorAdapterError(RuntimeError):
    """A prepared writing action has no confirmed mechanical disposition."""


@dataclass(frozen=True)
class AppliedReviewBatch:
    """Validated Docxtor batch plus action-to-operation correlation."""

    receipt: ReviewBatchReceipt
    operation_ids_by_action: dict[str, tuple[str, ...]]

    @property
    def data(self) -> bytes:
        return self.receipt.data


def apply_review_actions(
    data: bytes,
    document: ReviewDocument,
    actions: Sequence[ReviewAction],
    *,
    author: str = "Reviewer",
    revision_date: str | None = None,
) -> AppliedReviewBatch:
    """Apply effective writing actions as one all-or-nothing Docxtor batch.

    Actions must already have passed ReviewKit preparation and policy. This
    adapter does not reinterpret policy or silently skip an effective write.
    """
    commands: list[ReviewCommand] = []
    correlation: dict[str, tuple[str, ...]] = {}
    reviewer = RevisionAuthor(author=author, date=revision_date)
    for action in actions:
        if not _is_effective_write(action):
            continue
        locator, start, end = _mechanical_range(document, action)
        operation_id = f"{action.id}:revision"
        commands.append(
            ReviewCommand(
                operation_id=operation_id,
                mutate=_revision_mutation(action, locator, start, end, reviewer),
            )
        )
        correlation[action.id] = (operation_id,)

    try:
        receipt = apply_review_batch(data, commands)
    except (DocumentError, ReviewTransactionError, ValueError) as exc:
        raise DocxtorAdapterError(str(exc)) from exc
    _assert_receipts(receipt, correlation)
    return AppliedReviewBatch(receipt=receipt, operation_ids_by_action=correlation)


def _is_effective_write(action: ReviewAction) -> bool:
    return (
        action.action_type in WRITING_ACTIONS
        and action.status != ActionStatus.CONFLICT
        and action.metadata.get("blocked_from_corrected") is not True
    )


def _mechanical_range(document: ReviewDocument, action: ReviewAction) -> tuple[str, int, int]:
    matches = []
    for paragraph in document.iter_paragraphs():
        if action.node_id == paragraph.id or any(
            sentence.id == action.node_id for sentence in paragraph.sentences
        ):
            matches.append(paragraph)
    if len(matches) != 1 or not matches[0].locator:
        raise DocxtorAdapterError(
            f"action {action.id!r} does not resolve to one Docxtor paragraph locator"
        )
    paragraph = matches[0]
    paragraph_locator = paragraph.locator
    if paragraph_locator is None:
        raise DocxtorAdapterError(f"action {action.id!r} has no mechanical locator")
    action_locator = action.locator
    if (
        action_locator is not None
        and action_locator.char_start is not None
        and action_locator.char_end is not None
    ):
        return paragraph_locator, action_locator.char_start, action_locator.char_end
    original = action.original_text or ""
    if not original:
        offset = 0 if action.action_type == ReviewActionType.INSERT_BEFORE else len(paragraph.text)
        return paragraph_locator, offset, offset
    start = paragraph.text.find(original)
    if start < 0 or paragraph.text.find(original, start + 1) >= 0:
        raise DocxtorAdapterError(f"action {action.id!r} has no unique mechanical range")
    return paragraph_locator, start, start + len(original)


def _revision_mutation(
    action: ReviewAction,
    locator: str,
    start: int,
    end: int,
    reviewer: RevisionAuthor,
) -> Callable[[bytes], tuple[bytes, OperationReceipt]]:
    expected = action.original_text or None

    def mutate(data: bytes) -> tuple[bytes, OperationReceipt]:
        if action.action_type in {ReviewActionType.DELETE_TEXT, ReviewActionType.DELETE}:
            result = delete_revision(data, RevisionRange(locator, start, end, expected), reviewer)
            return result.data, result.receipt
        if action.action_type in {ReviewActionType.REPLACE_TEXT, ReviewActionType.REPLACE}:
            replacement = action.replacement_text or ""
            deleted, inserted = replace_revision(
                data, RevisionRange(locator, start, end, expected), replacement, reviewer
            )
            return inserted.data, _combine_receipts(deleted.receipt, inserted.receipt)
        if action.action_type in {
            ReviewActionType.INSERT_TEXT,
            ReviewActionType.INSERT_BEFORE,
            ReviewActionType.INSERT_AFTER,
        }:
            offset = end if action.action_type == ReviewActionType.INSERT_AFTER else start
            result = insert_revision(
                data, RevisionPosition(locator, offset), action.replacement_text or "", reviewer
            )
            return result.data, result.receipt
        raise DocxtorAdapterError(f"unsupported writing action: {action.action_type}")

    return mutate


def _combine_receipts(left: OperationReceipt, right: OperationReceipt) -> OperationReceipt:
    return OperationReceipt(
        operation="replace_revision",
        status=OperationStatus.APPLIED,
        affected_parts=tuple(sorted(set(left.affected_parts) | set(right.affected_parts))),
        created_ids=left.created_ids + right.created_ids,
        locator=right.locator,
        before_sha256=left.before_sha256,
        after_sha256=right.after_sha256,
        diagnostics=left.diagnostics + right.diagnostics,
    )


def _assert_receipts(receipt: ReviewBatchReceipt, correlation: dict[str, tuple[str, ...]]) -> None:
    operations = receipt.operations
    if len(operations) != sum(len(ids) for ids in correlation.values()):
        raise DocxtorAdapterError("Docxtor returned an incomplete operation receipt set")
    for action_id, operation_ids in correlation.items():
        for operation_id in operation_ids:
            index = next(
                (
                    i
                    for i, command_id in enumerate(_flatten(correlation))
                    if command_id == operation_id
                ),
                None,
            )
            if index is None or operations[index].status is not OperationStatus.APPLIED:
                raise DocxtorAdapterError(
                    f"writing action {action_id!r} has no applied mechanical receipt"
                )


def _flatten(correlation: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(operation_id for ids in correlation.values() for operation_id in ids)

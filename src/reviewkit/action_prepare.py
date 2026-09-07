"""Validate and prepare review actions against document text and policy."""

from __future__ import annotations

from collections.abc import Iterable

from reviewkit.action_demote import demote_edits_over_opaque_content, demote_overlapping_actions
from reviewkit.action_target import scope_paragraphs
from reviewkit.document import ReviewDocument
from reviewkit.models import ActionStatus, FindingLineageEvent, ReviewAction, ReviewActionType
from reviewkit.policy import WRITING_ACTIONS, ActionPolicy
from reviewkit.profile import ReviewProfile


def prepare_actions(
    document: ReviewDocument,
    profile: ReviewProfile,
    actions: Iterable[ReviewAction],
    policy: ActionPolicy | None = None,
) -> list[ReviewAction]:
    resolved_policy = policy if policy is not None else ActionPolicy.from_profile(profile)
    prepared = [_prepare_action(document, resolved_policy, action) for action in actions]
    prepared = demote_overlapping_actions(document, prepared)
    prepared = demote_edits_over_opaque_content(document, prepared)
    return [_record_policy_outcome(action) for action in prepared]


def _record_policy_outcome(action: ReviewAction) -> ReviewAction:
    event = FindingLineageEvent(
        kind="policy",
        scope=action.scope,
        node_id=action.node_id,
        parent_event_ids=tuple(event.event_id for event in action.lineage),
        decision=action.status.value,
        action_id=action.id,
    )
    return action.model_copy(update={"lineage": (*action.lineage, event)})


def _prepare_action(
    document: ReviewDocument,
    policy: ActionPolicy,
    action: ReviewAction,
) -> ReviewAction:
    conflict = _conflict_reason(document, action)
    if conflict:
        return action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, conflict),
                "policy_reason": conflict,
            }
        )

    node_text = document.get_node_text(action.node_id)
    if node_text is None:
        return action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(
                    action.reason, f"node_id does not exist: {action.node_id}"
                ),
                "policy_reason": f"node_id does not exist: {action.node_id}",
            }
        )

    # A section/document-scoped edit has no deterministic paragraph anchor unless it carries
    # original_text (both renderers apply writing actions at paragraph granularity). Without
    # one the corrected renderer silently drops it while should_apply_to_corrected/applied_count
    # still claim it, so the report over-claims and the artifacts diverge. Escalate instead.
    scope_conflict = _unanchorable_scope_edit_reason(document, action)
    if scope_conflict:
        return action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, scope_conflict),
                "policy_reason": scope_conflict,
            }
        )

    # An original_text found NOWHERE in the node can never be applied: str.replace would
    # silently no-op while the action is still reported APPLIED, so the report and stats
    # over-claim a fix that was never made. This is not the ambiguity the policy config
    # governs (that is MULTIPLE matches), so it fails closed to CONFLICT regardless of
    # ``auto_apply_requires_unique_match`` / ``ambiguous_edit_behavior``.
    missing = _missing_anchor_reason(node_text, action)
    if missing:
        return action.model_copy(
            update={
                "status": ActionStatus.CONFLICT,
                "reason": _append_reason(action.reason, missing),
                "policy_reason": missing,
            }
        )

    # Honor the profile's ambiguity config (previously declared but never consulted): only
    # gate on a non-unique match when ``auto_apply_requires_unique_match`` is set, and pick
    # the escalation status via ``ambiguous_edit_behavior`` (default CONFLICT).
    ambiguity = _ambiguous_match_reason(node_text, action)
    if ambiguity and policy.config.auto_apply_requires_unique_match:
        return action.model_copy(
            update={
                "status": _ambiguous_status(policy.config.ambiguous_edit_behavior),
                "reason": _append_reason(action.reason, ambiguity),
                "policy_reason": ambiguity,
            }
        )

    decision = policy.decide(action, node_text=node_text)
    metadata = dict(action.metadata)
    if decision.blocks_corrected:
        metadata["blocked_from_corrected"] = True
    return action.model_copy(
        update={
            "status": decision.status,
            "policy_reason": decision.reason,
            "metadata": metadata,
        }
    )


def _conflict_reason(document: ReviewDocument, action: ReviewAction) -> str | None:
    node_text = document.get_node_text(action.node_id)
    if node_text is None:
        return f"node_id does not exist: {action.node_id}"

    locator_reason = _locator_conflict_reason(node_text, action)
    if locator_reason:
        return locator_reason

    if (
        action.action_type
        in {
            ReviewActionType.REPLACE_TEXT,
            ReviewActionType.DELETE_TEXT,
            ReviewActionType.REPLACE,
            ReviewActionType.DELETE,
        }
        and not action.original_text
    ):
        return "original_text is required for replace/delete actions"

    if action.action_type in {
        ReviewActionType.REPLACE_TEXT,
        ReviewActionType.INSERT_TEXT,
        ReviewActionType.REPLACE,
        ReviewActionType.INSERT_BEFORE,
        ReviewActionType.INSERT_AFTER,
    }:
        if (
            action.action_type
            not in {
                ReviewActionType.INSERT_TEXT,
                ReviewActionType.INSERT_BEFORE,
            }
            and not action.replacement_text
        ):
            return "replacement_text is required for this action"
        if (
            action.action_type
            in {
                ReviewActionType.INSERT_TEXT,
                ReviewActionType.INSERT_BEFORE,
            }
            and action.replacement_text is None
        ):
            return "replacement_text is required for this action"

    return None


def _is_scope_level_node(document: ReviewDocument, node_id: str) -> bool:
    """True when ``node_id`` names the whole document or a section (not a paragraph/sentence)."""
    if node_id == document.id:
        return True
    return any(section.id == node_id for section in document.sections)


def _unanchorable_scope_edit_reason(document: ReviewDocument, action: ReviewAction) -> str | None:
    """Reason a section/document-scoped writing action cannot be applied deterministically.

    A scope-level writing action carrying ``original_text`` is routed to the paragraph
    where the quote lives (see ``actions_for_paragraph``); one WITHOUT it has no anchor,
    so the corrected renderer drops it while the stats still claim it. Escalate.

    The quote must also sit INSIDE one paragraph: both renderers apply edits at
    paragraph granularity, so a quote that only matches across a paragraph boundary
    (section text joins paragraphs with a separator) can never be applied and must
    fail closed here rather than blow up at render time.
    """
    if action.action_type not in WRITING_ACTIONS:
        return None
    if not _is_scope_level_node(document, action.node_id):
        return None
    if not action.original_text:
        return "section/document-scoped edits require original_text to anchor to a paragraph"
    if any(
        action.original_text in paragraph.text for paragraph in scope_paragraphs(document, action)
    ):
        return None
    return (
        "section/document-scoped edits require original_text that falls within a single "
        "paragraph to anchor deterministically"
    )


def _missing_anchor_reason(node_text: str, action: ReviewAction) -> str | None:
    """Reason a writing action's ``original_text`` anchor is absent from the node.

    Restricted to writing actions: comments are advisory and are routed only when their
    quote resolves to a paragraph, whereas an unmatched edit would be a silent no-op apply.
    """
    if action.action_type not in WRITING_ACTIONS:
        return None
    if not action.original_text or action.original_text in node_text:
        return None
    return f"original_text must match exactly once in node {action.node_id}; found 0 matches"


def _ambiguous_match_reason(node_text: str, action: ReviewAction) -> str | None:
    """Reason an edit is ambiguous because its ``original_text`` is not a unique anchor.

    A non-unique match means the applier cannot know which occurrence to edit. Returned
    as a distinct signal (not a hard structural conflict) so the caller can honor the
    profile's ``auto_apply_requires_unique_match`` / ``ambiguous_edit_behavior`` config.
    """
    if not action.original_text:
        return None
    matches = node_text.count(action.original_text)
    if matches == 1:
        return None
    return (
        f"original_text must match exactly once in node {action.node_id}; found {matches} matches"
    )


def _ambiguous_status(behavior: str) -> ActionStatus:
    # Fail closed: only an explicit human-decision opt-in downgrades the default CONFLICT.
    if behavior.strip().lower() in {"needs_human_decision", "human_decision"}:
        return ActionStatus.NEEDS_HUMAN_DECISION
    return ActionStatus.CONFLICT


def _locator_conflict_reason(node_text: str, action: ReviewAction) -> str | None:
    locator = action.locator
    if locator is None:
        return None
    if locator.node_id is not None and locator.node_id != action.node_id:
        return "locator node_id does not match action node_id"
    if locator.node_hash is not None and locator.node_hash != locator.hash_text(node_text):
        return "locator node_hash does not match current node text"
    if locator.char_start is None and locator.char_end is None:
        return None
    if locator.char_start is None or locator.char_end is None:
        return "locator char_start and char_end must be provided together"
    if locator.char_end < locator.char_start:
        return "locator char_end must be greater than or equal to char_start"
    if locator.char_end > len(node_text):
        return "locator range is outside the current node text"

    located_text = node_text[locator.char_start : locator.char_end]
    expected_text = locator.original_text or action.original_text
    if expected_text is not None and located_text != expected_text:
        return "locator text does not match current node text"
    if locator.text_hash is not None and locator.text_hash != locator.hash_text(located_text):
        return "locator text_hash does not match current node text"
    return None


def _append_reason(existing: str | None, addition: str) -> str:
    if existing:
        return f"{existing}; {addition}"
    return addition

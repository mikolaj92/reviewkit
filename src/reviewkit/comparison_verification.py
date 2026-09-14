"""comparison verification seams for DOCX provenance attribution."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from reviewkit.comparison_models import (
    ChangeProvenance,
    ComparisonProvenance,
    DocumentTransitionEvidence,
    ProvenanceDiagnostic,
    ProvenanceStatus,
    ReviewActionEvidence,
)
from reviewkit.document import ParagraphNode, ReviewDocument, SentenceNode
from reviewkit.models import ReviewAction, ReviewActionType, canonical_action_dump
from reviewkit.parser_docx import load_docx
from reviewkit.review_outcomes import revision_signatures

if TYPE_CHECKING:
    from docxtor import BlockPair, ComparisonDiagnostic, DocumentBlock, DocxDocumentComparison


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRE_LINEAGE_ACTION_FIELDS = frozenset(
    {
        "action_id",
        "action_type",
        "apply_hint",
        "apply_to_corrected",
        "category",
        "comment_text",
        "confidence",
        "evidence_refs",
        "finding_id",
        "locator",
        "metadata",
        "new_paragraph",
        "node_id",
        "original_text",
        "policy_reason",
        "priority",
        "reason",
        "references",
        "replacement_text",
        "requires_human_decision",
        "scope",
        "severity",
        "source_system",
        "status",
        "tags",
    }
)
_PREVIEW_DIAGNOSTIC_PARTS = ("numbering", "image", "media", "formatting")
_REPLACE_ACTIONS = {ReviewActionType.REPLACE_TEXT, ReviewActionType.REPLACE}
_DELETE_ACTIONS = {ReviewActionType.DELETE_TEXT, ReviewActionType.DELETE}
_INSERT_ACTIONS = {
    ReviewActionType.INSERT_TEXT,
    ReviewActionType.INSERT_BEFORE,
    ReviewActionType.INSERT_AFTER,
}


@dataclass(frozen=True)
class _Target:
    action: ReviewAction
    paragraph: ParagraphNode
    locator: str
    start: int
    end: int
    original: str
    insertion_point: int | None


@dataclass(frozen=True)
class _MappedAction:
    target: _Target
    pair_id: str
    left_block: DocumentBlock
    right_block: DocumentBlock
    start: int
    end: int
    insertion_point: int | None


@dataclass(frozen=True)
class _Chain:
    valid: bool
    pair_kind: str | None
    source_document: ReviewDocument | None
    codes: tuple[str, ...] = ()


def _verify_chain(
    comparison: DocxDocumentComparison,
    *,
    action_source: str | Path,
    review_evidence: ReviewActionEvidence | None,
    transition_evidence: DocumentTransitionEvidence | None,
    source_to_reviewed: DocxDocumentComparison | None,
) -> _Chain:
    if review_evidence is None:
        return _Chain(False, None, None, ("review_evidence_missing",))

    source_path = Path(action_source)
    try:
        source_bytes = source_path.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        source_document = load_docx(source_path)
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_hash:
            return _Chain(False, None, None, ("action_source_changed_during_read",))
        actual_signatures = revision_signatures(source_path)
    except Exception:  # noqa: BLE001 - malformed DOCX and parser failures must fail closed
        return _Chain(False, None, None, ("action_source_unreadable",))

    if not _valid_sha(source_hash) or source_hash != review_evidence.source_sha256:
        return _Chain(False, None, None, ("source_sha256_mismatch",))
    if not _valid_sha(review_evidence.reviewed_sha256):
        return _Chain(False, None, None, ("reviewed_sha256_invalid",))
    if not _valid_sha(review_evidence.actions_sha256):
        return _Chain(False, None, None, ("actions_sha256_invalid",))
    if any(not isinstance(action, ReviewAction) for action in review_evidence.actions):
        return _Chain(False, None, None, ("action_payload_invalid",))
    if len({action.id for action in review_evidence.actions}) != len(review_evidence.actions):
        return _Chain(False, None, None, ("duplicate_action_ids",))
    try:
        if not _action_digest_matches(review_evidence.actions, review_evidence.actions_sha256):
            return _Chain(False, None, None, ("actions_sha256_mismatch",))
    except (TypeError, ValueError):
        return _Chain(False, None, None, ("action_payload_invalid",))
    if Counter(actual_signatures) != Counter(review_evidence.source_revision_signatures):
        return _Chain(False, None, None, ("source_revision_signatures_mismatch",))

    left_hash = _comparison_hash(comparison, "left")
    right_hash = _comparison_hash(comparison, "right")
    if not _valid_sha(left_hash) or not _valid_sha(right_hash):
        return _Chain(False, None, None, ("comparison_package_unverified",))
    if _has_unreadable_diagnostic(_diagnostics(comparison)):
        return _Chain(False, None, None, ("comparison_package_unreadable",))

    if left_hash == source_hash and right_hash == review_evidence.reviewed_sha256:
        return _Chain(True, "input_to_reviewed", source_document)

    if transition_evidence is not None:
        if not _valid_sha(transition_evidence.input_sha256) or not _valid_sha(
            transition_evidence.output_sha256
        ):
            return _Chain(False, None, None, ("transition_sha256_invalid",))
        if transition_evidence.input_sha256 != review_evidence.reviewed_sha256:
            return _Chain(False, None, None, ("transition_input_sha256_mismatch",))
        if left_hash == source_hash and right_hash == transition_evidence.output_sha256:
            return _Chain(True, "input_to_corrected", source_document)
        if (
            left_hash == review_evidence.reviewed_sha256
            and right_hash == transition_evidence.output_sha256
        ):
            if source_to_reviewed is None:
                return _Chain(False, None, None, ("source_to_reviewed_comparison_missing",))
            if (
                _comparison_hash(source_to_reviewed, "left") != source_hash
                or _comparison_hash(source_to_reviewed, "right") != review_evidence.reviewed_sha256
            ):
                return _Chain(False, None, None, ("source_to_reviewed_hash_chain_mismatch",))
            if _has_unreadable_diagnostic(_diagnostics(source_to_reviewed)):
                return _Chain(False, None, None, ("source_to_reviewed_package_unreadable",))
            return _Chain(True, "reviewed_to_corrected", source_document)

    return _Chain(False, None, None, ("comparison_hash_chain_mismatch",))


def _targets(
    document: ReviewDocument,
    actions: Sequence[ReviewAction],
) -> dict[str, _Target | None]:
    paragraphs = {paragraph.id: paragraph for paragraph in document.iter_paragraphs()}
    sentences = {sentence.id: sentence for sentence in document.iter_sentences()}
    targets: dict[str, _Target | None] = {}
    for action in actions:
        paragraph = paragraphs.get(action.node_id)
        sentence = sentences.get(action.node_id)
        if paragraph is None and sentence is not None:
            paragraph = document.paragraph_for_sentence(sentence.id)
        if paragraph is None:
            targets[action.id] = None
            continue
        target = _target_for_action(action, paragraph, sentence)
        targets[action.id] = target
    return targets


def _target_for_action(
    action: ReviewAction,
    paragraph: ParagraphNode,
    sentence: SentenceNode | None,
) -> _Target | None:
    locator = paragraph.locator
    if not locator:
        return None
    node_text = sentence.text if sentence is not None else paragraph.text
    base = (sentence.char_start or 0) if sentence is not None else 0
    source_original = (
        (action.locator.original_text if action.locator else None) or action.original_text or ""
    )

    char_start = action.locator.char_start if action.locator else None
    char_end = action.locator.char_end if action.locator else None
    insertion_point: int | None = None
    if char_start is not None or char_end is not None:
        if char_start is None or char_end is None or char_end < char_start:
            return None
        locator_node = action.locator.node_id if action.locator else None
        if sentence is not None and locator_node != paragraph.id:
            if locator_node not in (None, sentence.id):
                return None
            if char_end > len(sentence.text):
                return None
            char_start += base
            char_end += base
        else:
            allowed_locator_nodes = {None, paragraph.id}
            if sentence is not None:
                allowed_locator_nodes.add(sentence.id)
            if locator_node not in allowed_locator_nodes:
                return None
        start, end = char_start, char_end
        selected_text = action.locator.original_text if action.locator else None
        expected = selected_text or action.original_text
        if expected and paragraph.text[start:end] != expected:
            return None
        if action.action_type in _INSERT_ACTIONS:
            insertion_point = end if action.action_type == ReviewActionType.INSERT_AFTER else start
    elif source_original:
        if node_text.count(source_original) != 1:
            return None
        relative_start = node_text.find(source_original)
        start = base + relative_start
        end = start + len(source_original)
        if action.action_type in _INSERT_ACTIONS:
            insertion_point = end if action.action_type == ReviewActionType.INSERT_AFTER else start
    elif action.action_type in _INSERT_ACTIONS:
        start = end = (
            0 if action.action_type == ReviewActionType.INSERT_BEFORE else len(paragraph.text)
        )
        insertion_point = start
    else:
        return None

    if start < 0 or end > len(paragraph.text):
        return None
    original = paragraph.text[start:end]
    if source_original and original != source_original:
        return None
    if action.action_type in (_REPLACE_ACTIONS | _DELETE_ACTIONS) and not original:
        return None
    return _Target(action, paragraph, locator, start, end, original, insertion_point)


def _map_direct_actions(
    comparison: DocxDocumentComparison,
    targets: dict[str, _Target | None],
) -> dict[str, _MappedAction | None]:
    mapped: dict[str, _MappedAction | None] = {}
    right_blocks = {block.id: block for block in comparison.right.blocks}
    for action_id, target in targets.items():
        if target is None:
            mapped[action_id] = None
            continue
        left_matches = [
            block
            for block in comparison.left.blocks
            if block.coordinate.container_id == target.locator
        ]
        if len(left_matches) != 1:
            mapped[action_id] = None
            continue
        left = left_matches[0]
        shift = _strip_shift(left.text, target.paragraph.text)
        if shift is None:
            mapped[action_id] = None
            continue
        start, end = target.start + shift, target.end + shift
        if end > len(left.text) or left.text[start:end] != target.original:
            mapped[action_id] = None
            continue
        pairs: tuple[BlockPair, ...] = tuple(
            pair for pair in comparison.block_pairs if pair.left_block_id == left.id
        )
        if len(pairs) != 1 or pairs[0].right_block_id is None:
            mapped[action_id] = None
            continue
        right = right_blocks.get(pairs[0].right_block_id)
        if right is None:
            mapped[action_id] = None
            continue
        insertion_point = (
            target.insertion_point + shift if target.insertion_point is not None else None
        )
        mapped[action_id] = _MappedAction(
            target, pairs[0].pair_id, left, right, start, end, insertion_point
        )
    return mapped


def _strip_shift(block_text: str, paragraph_text: str) -> int | None:
    if block_text == paragraph_text:
        return 0
    if block_text.strip() == paragraph_text:
        return len(block_text) - len(block_text.lstrip())
    return None


def _action_digest(actions: Sequence[ReviewAction]) -> str:
    return _payload_digest(canonical_action_dump(actions))


def _action_digest_matches(actions: Sequence[ReviewAction], expected: str) -> bool:
    if _action_digest(actions) == expected:
        return True

    # The previous public ReviewAction shape had no lineage field. Pydantic records
    # fields present in parsed sidecar JSON, so only an exact pre-lineage dump with
    # that field absent can use this compatibility digest. Current lineage values,
    # even empty ones, always use the current canonical action dump above.
    if not actions or any("lineage" in action.model_fields_set for action in actions):
        return False
    legacy = [
        action.model_dump(mode="json", by_alias=True, exclude_unset=True) for action in actions
    ]
    if any(frozenset(item) != _PRE_LINEAGE_ACTION_FIELDS for item in legacy):
        return False
    legacy.sort(key=lambda item: str(item.get("action_id", "")))
    return _payload_digest(legacy) == expected


def _payload_digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def _comparison_hash(comparison: DocxDocumentComparison, side: str) -> str:
    return str(getattr(getattr(comparison, side), "sha256", ""))


def _has_unreadable_diagnostic(diagnostics: Sequence[ProvenanceDiagnostic]) -> bool:
    return any(
        any(
            marker in diagnostic.code.lower()
            for marker in ("unreadable", "invalid_package", "unverified_package")
        )
        for diagnostic in diagnostics
    )


def _blocked_by_diagnostic(
    diagnostics: Sequence[ProvenanceDiagnostic],
    locator: str | None,
    event_type: str,
    *,
    pair_id: str | None = None,
) -> bool:
    if locator is None:
        return True
    for diagnostic in diagnostics:
        code = diagnostic.code.lower()
        if _is_preview_only_diagnostic(code):
            continue
        diagnostic_locator = diagnostic.locator
        if diagnostic_locator == locator or (pair_id and diagnostic_locator == pair_id):
            if _diagnostic_affects_event(code, event_type):
                return True
            continue
        if diagnostic_locator is not None:
            if _xpath_locator_matches(diagnostic_locator, locator):
                if _diagnostic_affects_event(code, event_type):
                    return True
                continue
            if code == "table_ordinal_alignment_coarse":
                table_indices = set(re.findall(r"table:(\d+)", diagnostic_locator))
                target_table = re.match(r"^table:(\d+)(?:\b|:)", locator)
                if (
                    target_table
                    and target_table.group(1) in table_indices
                    and _diagnostic_affects_event(code, event_type)
                ):
                    return True
                continue
            # A known physical locator or pair id identifies a different event
            # scope. Unknown locator formats are treated as unknown-scope semantic
            # warnings and handled conservatively below.
            if _is_known_physical_locator(diagnostic_locator) or diagnostic_locator.startswith(
                "pair-"
            ):
                continue
        # Unknown-scope semantic diagnostics may affect this event. Preview-only
        # warnings were filtered above; do not silently treat arbitrary locator
        # formats as unrelated.
        if _diagnostic_affects_event(code, event_type):
            return True
    return False


def _is_preview_only_diagnostic(code: str) -> bool:
    return any(fragment in code for fragment in _PREVIEW_DIAGNOSTIC_PARTS) or code in {
        "unsupported_object",
        "numbering_not_projected",
    }


def _diagnostic_affects_event(code: str, event_type: str) -> bool:
    if event_type == "text":
        return any(
            marker in code
            for marker in (
                "paragraph_projection",
                "unsupported_inline",
                "text_diff",
                "alignment",
                "table_ordinal",
                "coverage_incomplete",
            )
        )
    if event_type == "revision":
        return any(
            marker in code
            for marker in (
                "revision",
                "markup_coverage",
                "unsupported_inline",
                "paragraph_projection",
                "alignment",
                "table_ordinal",
            )
        )
    if event_type == "comment":
        return any(
            marker in code
            for marker in (
                "comment",
                "paragraph_projection",
                "alignment",
                "unsupported_inline",
                "table_ordinal",
            )
        )
    return any(marker in code for marker in ("formatting", "paragraph_projection", "alignment"))


def _xpath_locator_matches(diagnostic_locator: str, physical_locator: str) -> bool:
    """Map a simple body paragraph XPath to Docxtor's zero-based body locator."""
    if not physical_locator.startswith("body:p:"):
        return False
    match = re.search(r"(?:^|/)w:p\[(\d+)\](?:/|$)", diagnostic_locator)
    return bool(match and physical_locator == f"body:p:{int(match.group(1)) - 1}")


def _is_known_physical_locator(locator: str) -> bool:
    return bool(re.match(r"^(?:body|table|header|footer|footnote|endnote|comment):", locator))


def _diagnostics(comparison: DocxDocumentComparison) -> tuple[ProvenanceDiagnostic, ...]:
    sources: tuple[ComparisonDiagnostic, ...] = (
        *comparison.diagnostics,
        *comparison.left.diagnostics,
        *comparison.right.diagnostics,
    )
    result: list[ProvenanceDiagnostic] = []
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for item in sources:
        value = (item.code, item.side, item.part_name, item.locator)
        if value in seen:
            continue
        seen.add(value)
        result.append(ProvenanceDiagnostic(*value))
    return tuple(result)


def _merge_diagnostics(
    first: Sequence[ProvenanceDiagnostic], second: Sequence[ProvenanceDiagnostic]
) -> tuple[ProvenanceDiagnostic, ...]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    merged = []
    for item in (*first, *second):
        key = (item.code, item.side, item.part_name, item.locator)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return tuple(merged)


def _empty_rows(comparison: DocxDocumentComparison) -> dict[str, ChangeProvenance]:
    rows: dict[str, ChangeProvenance] = {}
    for event_type, events in (
        ("text", comparison.text_changes),
        ("comment", comparison.comment_changes),
        ("revision", comparison.revision_events),
        ("formatting", comparison.formatting_changes),
    ):
        for event in events:
            rows[event.change_id] = ChangeProvenance(
                event.change_id,
                event_type,
                ProvenanceStatus.UNKNOWN,
                evidence_codes=("no_exact_provenance_match",),
            )
    return rows


def _result(
    comparison: DocxDocumentComparison,
    diagnostics: tuple[ProvenanceDiagnostic, ...],
    rows: dict[str, ChangeProvenance],
) -> ComparisonProvenance:
    ordered = tuple(rows.values())
    return ComparisonProvenance(
        comparison.comparison_id,
        comparison.left.sha256,
        comparison.right.sha256,
        diagnostics,
        ordered,
    )

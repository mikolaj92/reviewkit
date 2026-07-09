"""Public API for ReviewKit."""

from reviewkit.anchors import (
    ANCHOR_LAST,
    SignatureBlockStart,
    find_body_paragraph,
    find_paragraph_by_locator,
    find_signature_block_start,
    is_supported_anchor,
    parse_body_anchor_index,
)
from reviewkit.context import (
    EmptyReviewContextProvider,
    ReviewContext,
    ReviewContextProvider,
)
from reviewkit.document import ReviewDocument
from reviewkit.insertions import (
    InsertionAction,
    InsertionKind,
    InsertionReport,
    InsertionResult,
    InsertionValidator,
    ParagraphInserter,
    SUGGESTION_MARKER_PREFIX,
    contains_suggestion_marker,
    format_suggestion_text,
)
from reviewkit.llm import LLMClient, MockLLMClient
from reviewkit.markup_purity import (
    MarkupReport,
    has_comments,
    has_suggestion_marker,
    has_tracked_revisions,
    inspect_markup,
)
from reviewkit.models import (
    ActionStatus,
    EvidenceRef,
    ReviewAction,
    ReviewActionType,
    ReviewDimension,
    ReviewFinding,
    ReviewLocator,
    ReviewReference,
    ReviewResponse,
    ReviewResult,
    ReviewScope,
    ReviewStats,
    canonical_action_dump,
)
from reviewkit.parser_docx import DocxComment, DocxFootnote, read_comments, read_footnotes
from reviewkit.pipeline import review_document
from reviewkit.policy import ActionPolicy, PolicyGuard
from reviewkit.profile import ActionPolicyConfig, ReviewProfile, load_profile
from reviewkit.renderer_docx import RenderIntegrityError
from reviewkit.revisions import (
    AcceptRevisionsError,
    accept_all_revisions,
    apply_reviewed_markup,
)

__all__ = [
    "ANCHOR_LAST",
    "AcceptRevisionsError",
    "ActionPolicy",
    "ActionPolicyConfig",
    "ActionStatus",
    "DocxComment",
    "DocxFootnote",
    "EmptyReviewContextProvider",
    "EvidenceRef",
    "InsertionAction",
    "InsertionKind",
    "InsertionReport",
    "InsertionResult",
    "InsertionValidator",
    "LLMClient",
    "MarkupReport",
    "PolicyGuard",
    "MockLLMClient",
    "ParagraphInserter",
    "RenderIntegrityError",
    "SUGGESTION_MARKER_PREFIX",
    "ReviewAction",
    "ReviewActionType",
    "ReviewContext",
    "ReviewContextProvider",
    "ReviewDimension",
    "ReviewDocument",
    "ReviewFinding",
    "ReviewLocator",
    "ReviewProfile",
    "ReviewReference",
    "ReviewResponse",
    "ReviewResult",
    "ReviewScope",
    "ReviewStats",
    "SignatureBlockStart",
    "accept_all_revisions",
    "apply_reviewed_markup",
    "canonical_action_dump",
    "contains_suggestion_marker",
    "find_body_paragraph",
    "find_paragraph_by_locator",
    "find_signature_block_start",
    "format_suggestion_text",
    "has_comments",
    "has_suggestion_marker",
    "has_tracked_revisions",
    "inspect_markup",
    "is_supported_anchor",
    "load_profile",
    "parse_body_anchor_index",
    "read_comments",
    "read_footnotes",
    "review_document",
]

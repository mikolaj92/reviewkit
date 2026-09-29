"""Public API for ReviewKit.

0.24 is a domain-generic review process: Pack + two scans + plugin sockets.
The same engine reviews any Pack; core does not encode a statute or product
domain.

Hosts import typed objects from this package and pass instances:

* schemas: ``Pack``, ``Ontology``, ``Function``, ``SourceUnit``, ``Rule``
* plugin sockets: ``DecisionClient.decide``, ``LLMClient.complete_json``
* decision payloads: ``FragmentDecisionState``, ``DocumentDecisionState``
* fakes: ``MockDecisionClient``, ``MockLLMClient``
* entry points: ``review_tree``, ``review_source``, ``review_document``
* naming/judge types: ``FunctionTag``, ``NamingResponse``, ``Verdict``,
  ``VerdictKind``, ``ActionText``, ``ReviewState`` (``covered()``)

JSON files load through ``Pack.model_validate`` / ``Pack.model_validate_json``
only. ``detect()`` is not a host API. Helpers such as ``judge_rules`` and
``naming_questions`` stay on ``reviewkit.pack`` and ``reviewkit.decision``.
"""

from reviewkit.anchors import (
    ANCHOR_LAST,
    is_supported_anchor,
    parse_body_anchor_index,
)
from reviewkit.artifact_preservation import (
    ReviewArtifactPreservationError,
    assert_docx_structure_preserved,
)
from reviewkit.artifact_purity import ReviewArtifactPurityAssessment, assess_review_artifact_purity
from reviewkit.comment_remarks import (
    RemarkDisposition,
    RemarkWeight,
    ReviewRemark,
    compare_review_remarks,
    remark_disposition,
    remark_weight,
    review_remarks,
)
from reviewkit.comments import DocxComment, comments_for_locator, read_comments
from reviewkit.comparison import attribute_docx_changes
from reviewkit.comparison_models import (
    ChangeProvenance,
    ComparisonProvenance,
    DocumentTransitionEvidence,
    ProvenanceDiagnostic,
    ProvenanceStatus,
    ReviewActionEvidence,
)
from reviewkit.context import (
    EmptyReviewContextProvider,
    ReviewContext,
    ReviewContextProvider,
)
from reviewkit.decision import (
    ChoiceQuestion,
    DecisionAnswer,
    DecisionCall,
    DecisionClient,
    DecisionState,
    DocumentDecisionState,
    FragmentDecisionState,
    MockDecisionClient,
    NoulQuestion,
    Question,
)
from reviewkit.document import DocumentParser, ReviewDocument
from reviewkit.finality import (
    ReviewFinalityAssessment,
    ReviewFinalityStatus,
    assess_review_finality,
)
from reviewkit.insertions import (
    SUGGESTION_MARKER_PREFIX,
    InsertionAction,
    InsertionKind,
    contains_suggestion_marker,
    format_suggestion_text,
)
from reviewkit.llm import (
    LLMCapabilities,
    LLMClient,
    LLMClientError,
    LLMClientFailure,
    LLMRequestOptions,
    MockLLMClient,
    StructuredOutputMode,
)
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
    FindingLineageEvent,
    ReviewAction,
    ReviewActionType,
    ReviewBoundError,
    ReviewDimension,
    ReviewFailureClass,
    ReviewFinding,
    ReviewLocator,
    ReviewReference,
    ReviewResponse,
    ReviewResult,
    ReviewScope,
    ReviewStats,
    RevisionCoverageError,
    RevisionCoverageState,
    RevisionLedger,
    SourceRevision,
    SourceRevisionKind,
    canonical_action_dump,
)
from reviewkit.pack import (
    ActionText,
    Function,
    FunctionTag,
    NamingResponse,
    Ontology,
    Pack,
    PassTrace,
    ProcessCheck,
    Rule,
    SourceUnit,
    Verdict,
    VerdictKind,
)
from reviewkit.parser_docx import DocxDocumentParser, DocxFootnote, load_docx, read_footnotes
from reviewkit.parser_text import TextDocumentParser, parse_text
from reviewkit.pipeline import review_document
from reviewkit.policy import ActionPolicy, PolicyGuard
from reviewkit.portable_trail import (
    PortableReviewTrailError,
    PortableReviewTrailProfile,
    append_portable_review_trail,
    has_portable_review_trail,
    strip_portable_review_trail,
    write_portable_review_trail,
)
from reviewkit.profile import ActionPolicyConfig, ReviewProfile, load_profile
from reviewkit.renderer_docx import RenderIntegrityError
from reviewkit.review import review_source, review_tree
from reviewkit.review_outcomes import (
    IncorporatedCommentOutcome,
    RenderedActionAssessment,
    ReviewChangeMetrics,
    assess_rendered_actions,
    incorporated_comment_outcomes,
    measure_review_changes,
    read_metadata_marker,
    revision_signatures,
    set_metadata_marker,
    strip_metadata_marker,
)
from reviewkit.revision_rejection import RejectRevisionsError, reject_all_revisions
from reviewkit.revisions import (
    AcceptRevisionsError,
    accept_all_revisions,
    apply_reviewed_markup,
)
from reviewkit.state import ReviewState
from reviewkit.takt_reviewer import TaktReviewer

__all__ = [
    "ANCHOR_LAST",
    "SUGGESTION_MARKER_PREFIX",
    "AcceptRevisionsError",
    "ActionPolicy",
    "ActionPolicyConfig",
    "ActionStatus",
    "ActionText",
    "ChangeProvenance",
    "ChoiceQuestion",
    "ComparisonProvenance",
    "DecisionAnswer",
    "DecisionCall",
    "DecisionClient",
    "DecisionState",
    "DocumentDecisionState",
    "DocumentParser",
    "DocumentTransitionEvidence",
    "DocxComment",
    "DocxDocumentParser",
    "DocxFootnote",
    "EmptyReviewContextProvider",
    "EvidenceRef",
    "FindingLineageEvent",
    "FragmentDecisionState",
    "Function",
    "FunctionTag",
    "IncorporatedCommentOutcome",
    "InsertionAction",
    "InsertionKind",
    "LLMCapabilities",
    "LLMClient",
    "LLMClientError",
    "LLMClientFailure",
    "LLMRequestOptions",
    "MarkupReport",
    "MockDecisionClient",
    "MockLLMClient",
    "NamingResponse",
    "NoulQuestion",
    "Ontology",
    "Pack",
    "PassTrace",
    "PolicyGuard",
    "PortableReviewTrailError",
    "PortableReviewTrailProfile",
    "ProcessCheck",
    "ProvenanceDiagnostic",
    "ProvenanceStatus",
    "Question",
    "RejectRevisionsError",
    "RemarkDisposition",
    "RemarkWeight",
    "RenderIntegrityError",
    "RenderedActionAssessment",
    "ReviewAction",
    "ReviewActionEvidence",
    "ReviewActionType",
    "ReviewArtifactPreservationError",
    "ReviewArtifactPurityAssessment",
    "ReviewBoundError",
    "ReviewChangeMetrics",
    "ReviewContext",
    "ReviewContextProvider",
    "ReviewDimension",
    "ReviewDocument",
    "ReviewFailureClass",
    "ReviewFinalityAssessment",
    "ReviewFinalityStatus",
    "ReviewFinding",
    "ReviewLocator",
    "ReviewProfile",
    "ReviewReference",
    "ReviewRemark",
    "ReviewResponse",
    "ReviewResult",
    "ReviewScope",
    "ReviewState",
    "ReviewStats",
    "RevisionCoverageError",
    "RevisionCoverageState",
    "RevisionLedger",
    "Rule",
    "SourceRevision",
    "SourceRevisionKind",
    "SourceUnit",
    "StructuredOutputMode",
    "TaktReviewer",
    "TextDocumentParser",
    "Verdict",
    "VerdictKind",
    "accept_all_revisions",
    "append_portable_review_trail",
    "apply_reviewed_markup",
    "assert_docx_structure_preserved",
    "assess_rendered_actions",
    "assess_review_artifact_purity",
    "assess_review_finality",
    "attribute_docx_changes",
    "canonical_action_dump",
    "comments_for_locator",
    "compare_review_remarks",
    "contains_suggestion_marker",
    "format_suggestion_text",
    "has_comments",
    "has_portable_review_trail",
    "has_suggestion_marker",
    "has_tracked_revisions",
    "incorporated_comment_outcomes",
    "inspect_markup",
    "is_supported_anchor",
    "load_docx",
    "load_profile",
    "measure_review_changes",
    "parse_body_anchor_index",
    "parse_text",
    "read_comments",
    "read_footnotes",
    "read_metadata_marker",
    "reject_all_revisions",
    "remark_disposition",
    "remark_weight",
    "review_document",
    "review_remarks",
    "review_source",
    "review_tree",
    "revision_signatures",
    "set_metadata_marker",
    "strip_metadata_marker",
    "strip_portable_review_trail",
    "write_portable_review_trail",
]

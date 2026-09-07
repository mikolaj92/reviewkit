# Fallback inventory

This inventory records remaining promoted compatibility, legacy, shim, and
degraded-output paths. Normal validation defaults and optional document fields
are not fallback paths. Completed deletions are not listed: the named
compatibility aliases are gone from `src/reviewkit/`.

| Symbol/path | Decision | Reason / coverage |
| --- | --- | --- |
| Precise text comment anchoring to whole-paragraph comments in `renderer_docx` | **Promote** | Explicit degraded-output behavior: if an advisory quote cannot be precisely marked, retain the review feedback on the containing paragraph rather than drop it. Precise anchoring around opaque content is covered by `test_precise_comment_anchor_survives_opaque_segment_before_the_quote`. |
| Unanchored scope actions in `renderer_docx` | **Promote** | Explicit reviewed-artifact feature: actions receive a labelled comment on a generated review-note paragraph; covered by scoped advisory and cross-paragraph conflict tests. |
| Overlap-consumed suggestions in `renderer_docx` | **Promote** | Explicit conflict-comment behavior, covered by `test_overlap_consumed_suggestion_degrades_to_comment_not_error`. |
| Required `--llm` and Takt import errors | **Promote** | Explicit configuration/error behavior; there is no local engine fallback. Covered by CLI and Takt integration tests. |

No one-shot data migrations were found. Structural `getattr` uses around document
nodes, LLM responses, and optional fields are boundary handling, not compatibility
implementations; they remain subject to their existing parser/renderer tests.

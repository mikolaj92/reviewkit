# Fallback inventory

This inventory records the compatibility, legacy, shim, and degraded-output paths audited
for issue #176. Normal validation defaults and optional document fields are not fallback
paths.

| Symbol/path | Decision | Reason / coverage |
| --- | --- | --- |
| `homeostat.profile_to_homeostats` | **Delete** | Unused compatibility name superseded by `profile_to_layer_specs`. |
| `homeostat.build_layered_homeostats` | **Delete** | Unused compatibility adapter superseded by `build_layer_specs`. |
| `plant._DocNode` | **Delete** | Unused private compatibility alias; `DocNode` is the documented type. |
| `renderer_docx._add_comment` plain-text degradation | **Delete** | A malformed/unsupported comment API must fail rendering rather than silently produce a different artifact. |
| `InsertionValidator` malformed OOXML reporting | **Promote** | Explicit fail-closed integrity feature, covered by `test_check_document_integrity_missing_body` and the empty-document integrity test. |
| Unanchored scope actions in `renderer_docx` | **Promote** | Explicit reviewed-artifact feature: actions receive a labelled comment on a generated review-note paragraph; covered by scoped advisory and cross-paragraph conflict tests. |
| Overlap-consumed suggestions in `renderer_docx` | **Promote** | Explicit conflict-comment behavior, covered by `test_overlap_consumed_suggestion_degrades_to_comment_not_error`. |
| Required `--llm` and Takt import errors | **Promote** | Explicit configuration/error behavior; there is no local engine fallback. Covered by CLI and Takt integration tests. |

No one-shot data migrations were found. Structural `getattr` uses around python-docx objects and
optional fields are boundary handling, not compatibility implementations; they remain subject to
their existing parser/renderer tests.

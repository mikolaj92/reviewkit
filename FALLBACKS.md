# Fallback inventory

This inventory records remaining promoted compatibility, legacy, shim, and
degraded-output paths. Normal validation defaults and optional document fields
are not fallback paths. Completed deletions are not listed: the named
compatibility aliases are gone from `src/reviewkit/`.

| Symbol/path | Decision | Reason / coverage |
| --- | --- | --- |
| Second live comment on a sentence whose range markers are already opaque in `live_docx.add_comment` | **Promote** | A later stay on the same zdanie still adds a Word comment: Docxtor cannot place two identical ranges, so the extra comment is written on the paragraph and still sits on the sentence. Covered by `test_review_walks_one_docx_in_place`. |

No one-shot data migrations were found.

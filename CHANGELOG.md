# Changelog

## Unreleased

`review_docx` walks **one DOCX in place**. That walk is the review: zdanie,
then akapit, then rozdział, then całość *n* times, each with a stay-or-go
loop. Side effects (add / update / delete a comment, change text) land on
that same file during the walk. This is not nested post-order of an
abstract tree with a new `reviewed.docx` only after both Pack scans.

Docs now match the 0.24.1 Pack surface: `review_tree` / `review_source` /
`review_document` / `TaktReviewer` / CLI, plus `LLMClient.capabilities` and
`LLMRequestOptions`. Removed insertion-engine claims the package no longer
exports, and the unimplemented local takt source-checkout knob. Comment
balloon offsets no longer import python-docx; physical DOCX stays behind
Docxtor. Reviewed-comment `anchor_text` accepts a missing original quote
(`str | None`), so `uv run mypy` is clean.

## 0.24.1

Breaking cleanup of the public review API. Pack + `DecisionClient` +
`LLMClient` is the only path. The fused `pack=None` single-pass is gone.

0.24 is a refined generic review process (Pack + two scans + plugin
sockets), not a legal domain in core. The same engine reviews a privacy notice or a newspaper article; only Pack content changes. Pack schema stays
abstract: functions, rules, units.

Host contract: construct typed `Pack` / `Ontology` / `Rule` / `SourceUnit`
in Python (or `Pack.model_validate` / `Pack.model_validate_json` once at the
file edge). Do not hand-decode JSON dicts in the pipeline. See the README
and [`docs/host-integration.md`](docs/host-integration.md).

### Removed

- `pack=None` fused `complete_json` of findings+actions per node, including
  the fused reconciliation loop on that path.
- Optional `pack` / `decision` defaults on `review_tree`, `review_source`,
  `review_document`, and `TaktReviewer`. All four require typed `Pack` and
  `DecisionClient` instances.

### Host contract

- Call site: `review_tree(document, profile, llm, pack, decision)`.
- Decision payloads are frozen Pydantic models (`FragmentDecisionState`,
  `DocumentDecisionState`) holding a typed `SourceUnit | None`, not JSON
  dict dumps.
- CLI requires `--pack`, `--decision`, and `--llm`. Pack JSON is loaded with
  `Pack.model_validate_json` at the edge.

### Docs / examples

Scientific paper review ships as a first-class **example Pack** (not a core
domain): [`docs/platforms/scientific-paper-review.md`](docs/platforms/scientific-paper-review.md),
[`examples/packs/scientific_paper.json`](examples/packs/scientific_paper.json),
[`examples/profiles/scientific.reviewer`](examples/profiles/scientific.reviewer).
Egg fixture [`examples/papers/egg-low-quality.md`](examples/papers/egg-low-quality.md)
and sketch [`examples/scientific_paper_review.py`](examples/scientific_paper_review.py)
exercise name → judge → act through `MockDecisionClient` / `MockLLMClient`.

### Fixes

Pack two-scan loop: name does not touch the effector; judge short-circuits
covered / unmatched nodes before takt; `missing` and below-confidence
verdicts do not call `LLMClient`; act-plugin failures degrade to a person
with a structured trace; re-runs reset traces.

Typing and public-export polish for the Pack path. Hosts import Pack schemas,
plugin sockets, and review entry points from `reviewkit`.

## 0.24.0

Breaking change. A review given a `Pack` runs two scans plus an optional write.
The host injects model plugins; ReviewKit does not ship a model runtime.

Host guide: load Pack → inject `DecisionClient` → two scans. See the README
and [`docs/host-integration.md`](docs/host-integration.md). Gaps are
`ontology.function_ids() − covered()` on the host, not `missing_elements`.
`ReviewFinding.dimension` is not a function id. `detect()` is internal.

### Pack

`Pack` is the game: `ontology` + `rules` + `units`. It is not the profile, not
`instructions.md`, and not `external_review_context`.

- `Ontology.functions` is the dictionary (`Function.id` / `label` / `attach_to`).
- `SourceUnit.force` is data (`binding`, `dead`, …).
- Unified `Rule`: `kind` (`label` | `close` | `defect`), `scope`
  (`fragment` | `document`), `when` (`always` | `function_present` |
  `function_absent`), optional `source_unit_id`.
- Validators: `function_id` belongs to the ontology; `source_unit_id` belongs
  to `units`. Close is document-scope; label and defect are fragment-scope.

### Two-scan review

The intended path always receives a pack.

1. **Name** every sentence, paragraph, section, and document through
   `DecisionClient.decide` (one noul per function). `NamingResponse` is tags
   only — no findings, no actions, not `RawSignal`, not `ReviewFinding.dimension`.
2. **Judge** matching `when` rules and the one cited `SourceUnit`. Close /
   `function_absent` runs only on the document, and only when
   `ReviewState.covered()` has no nodes for that function. Gaps are
   `ontology.function_ids − covered()`, computed on the host.
3. **Act** through `LLMClient.complete_json` only for `change` / `delete` /
   `insert` above the profile confidence floor. Otherwise a person.

Effector materializes scan-2 actions only.

### Plugin sockets

- `DecisionClient.decide(state, questions)` — host plugin for name and judge.
- `LLMClient.complete_json(messages, schema)` — host plugin for replacement text.
- Call site: `review_tree(..., pack=..., decision=..., llm=...)`.

Core does not import or bundle Basal, Qwen, Jev, vLLM, URLs, or weight names.
Tests use `MockDecisionClient` and `MockLLMClient` only.

### Compatibility

`pack=None` remained explicit legacy compat in 0.24.0: one fused
`complete_json` per node into `*ReviewResponse`. Removed in 0.24.1.

### Dependencies

Pydantic `>=2.13.5,<2.14`. Takt `v0.3.2`. Docxtor `v0.14.3`.

Earlier notes live under [`docs/releases/`](docs/releases/).

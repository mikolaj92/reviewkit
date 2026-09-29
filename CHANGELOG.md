# Changelog

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

`pack=None` remains explicit legacy compat: one fused `complete_json` per node
into `*ReviewResponse`. A pack review requires an injected `DecisionClient`.

### Dependencies

Pydantic `>=2.13.5,<2.14`. Takt `v0.3.2`. Docxtor `v0.14.3`.

Earlier notes live under [`docs/releases/`](docs/releases/).

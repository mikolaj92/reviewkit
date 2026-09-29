# Host integration: Pack + two scans

ReviewKit 0.24 reviews through a **Pack** and two host-injected sockets. The
host (Temida, or any app) owns domain data and model plugins. This library
does not review domain content itself.

## Call site

```text
Pack load  →  inject DecisionClient  →  two scans (name, then judge)
                                         → optional LLMClient act
```

```python
from reviewkit import Pack, load_profile, review_document, review_tree
from reviewkit.takt_reviewer import TaktReviewer

pack = Pack.model_validate_json(pack_json)
profile = load_profile(profile_dir)  # behavior only

# Artifacts:
review_document(..., profile_path=profile, llm=llm, pack=pack, decision=decision)
review_tree(document, profile, llm, pack=pack, decision=decision)

# Tag map / gaps (host sitko):
findings, actions, state = TaktReviewer(
    profile=profile, llm=llm, pack=pack, decision=decision,
).review(document)
gaps = pack.ontology.function_ids() - set(state.covered())
```

A Pack review raises if `decision` is omitted. `llm` is still required: scan 3
writes replacement text through `LLMClient.complete_json`.

Runnable sketch: [`examples/host_pack_review.py`](../examples/host_pack_review.py).
Example Pack: [`examples/packs/story.json`](../examples/packs/story.json).
Example profile (behavior only):
[`examples/profiles/story.teacher`](../examples/profiles/story.teacher).

## What each object is

| Object | Contains | Does not contain |
| --- | --- | --- |
| `Pack` | `Ontology` (function dictionary), `SourceUnit`s, `Rule`s | Reviewer tone, action policy, pipeline |
| `ReviewProfile` | Role, language, document type, pipeline, action policy | Acts, function ids, source text |
| `DecisionClient` | Host plugin for name + judge (`decide`) | A ReviewKit-owned model server |
| `LLMClient` | Host plugin for replacement text (`complete_json`) | Naming or judging on a Pack path |

`instructions.md`, `profile.toml`, and `external_review_context` are **not**
the review payload. Putting required clauses or source acts in profile
markdown does not load a Pack.

## Scan 1 — name

Every enabled sentence, paragraph, section, and document is named against the
whole ontology (`naming_functions`). The host plugin answers one noul question
per `Function.id`. `NamingResponse` is `{tags}` only: no findings, no actions.
Accepted tags land on `ReviewState.tags`. They are not written to `RawSignal`.

## Scan 2 — judge

Matching `when` / `scope` rules run, each with at most the one `SourceUnit` it
cites.

- Fragment: `defect` (and never `close`, never `function_absent`).
- Document: `close` / `function_absent` only when `covered()` has no nodes for
  that function.

Verdicts are `keep` / `change` / `delete` / `insert` / `missing`. Findings
created from verdicts use the verdict kind as title and the function id as
description. **Do not** store a function id in `ReviewFinding.dimension`.

## Scan 3 — act (optional)

`LLMClient.complete_json` runs only for `change` / `delete` / `insert` whose
confidence is at or above the profile floor. Below the floor the action goes
to a person (`requires_human_decision`, no replacement text).

## Host gaps

```python
gaps = pack.ontology.function_ids() - set(state.covered())
```

`ReviewState.missing_elements` is leftover from the fused pass. It is not the
legal/domain gap API.

## What not to do

- Call `detect()` from host code. It is an internal plant adapter.
- Treat `ReviewFinding.dimension` as a function id.
- Treat `missing_elements` as ontology gaps.
- Fold Pack into `instructions.md`, `external_review_context`, or
  `profile.toml`.
- Expect one fused `complete_json` of findings+actions per sentence when a
  Pack is present.
- Import a model runtime, weight name, or server URL from `src/reviewkit`.
  Plugins are injected at the call site; tests use mocks only.
- Run `CloseRule` / “missing function X” at sentence scope. Absence is judged
  once, on the document, from `covered()`.

## Legacy: `pack=None`

Omitting `pack` keeps the pre-0.24 single fused `complete_json` per node into
`*ReviewResponse`. Profile markdown and `ReviewContextProvider` still feed
that path. The CLI (`reviewkit input.docx --profile ... --llm ...`) is this
fused path. New hosts should pass `pack` and `decision`.

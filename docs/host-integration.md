# Host integration: Pack + two scans

ReviewKit 0.24.1 is a generic review **process**: Pack + two scans +
`DecisionClient` / `LLMClient` sockets. The same engine reviews a privacy notice or a newspaper article; only Pack content changes. The host owns
domain data and model plugins. This library does not review domain content
itself and does not encode a statute.

Hosts pass **Python objects**. Import `Pack`, `DecisionClient`, `LLMClient`,
and the rules/units models, then pass typed instances. Do not hand-decode JSON
dicts into the call site. A Pack file may be loaded with
`Pack.model_validate` / `Pack.model_validate_json` only.

## Call site

```text
Pack (typed object)  →  inject DecisionClient  →  two scans (name, then judge)
                                                 → optional LLMClient act
```

```python
from reviewkit import (
    DecisionClient,
    DocumentDecisionState,
    FragmentDecisionState,
    Function,
    LLMClient,
    Ontology,
    Pack,
    Rule,
    SourceUnit,
    TaktReviewer,
    load_profile,
    review_document,
    review_tree,
)

pack = Pack(
    ontology=Ontology(functions=[Function(id="lead", label="Lead", attach_to=["sentence"])]),
    units={
        "u1": SourceUnit(
            id="u1",
            source_id="host",
            locator="§1",
            text="Lead source.",
            force="binding",
        )
    },
    rules=[
        Rule(
            id="defect-lead",
            kind="defect",
            function_id="lead",
            scope="fragment",
            when="function_present",
            source_unit_id="u1",
        )
    ],
)
# File form only:
# pack = Pack.model_validate_json(pack_json)
profile = load_profile(profile_dir)  # behavior only

review_document(input_path, profile, llm, pack, decision)
review_tree(document, profile, llm, pack, decision)

findings, actions, state = TaktReviewer(
    profile=profile, llm=llm, pack=pack, decision=decision,
).review(document)
gaps = pack.ontology.function_ids() - set(state.covered())
```

`pack` and `decision` are required. `llm` writes replacement text through
`LLMClient.complete_json`.

A `DecisionClient.decide` plugin receives `str` (name) or a
`FragmentDecisionState` / `DocumentDecisionState` (judge), including the cited
`SourceUnit` when a rule has one:

```python
def decide(self, state, questions):
    if isinstance(state, FragmentDecisionState):
        unit = state.unit  # SourceUnit | None
        text = state.text
    elif isinstance(state, DocumentDecisionState):
        unit = state.unit
        covered = state.covered
    ...
```

Runnable sketch: [`examples/host_pack_review.py`](../examples/host_pack_review.py).
Example Packs:
[`examples/packs/story.json`](../examples/packs/story.json) (story),
[`examples/packs/scientific_paper.json`](../examples/packs/scientific_paper.json)
(scientific paper). Example profiles (behavior only):
[`examples/profiles/story.teacher`](../examples/profiles/story.teacher),
[`examples/profiles/scientific.reviewer`](../examples/profiles/scientific.reviewer).

## Platforms

ReviewKit is a platform engine. Hosts own domain Packs and plugins.

| Surface | Owns | Not in ReviewKit core |
| --- | --- | --- |
| **Legal host (Temida)** | Legal ontology, source acts, label/defect/close rules, `DecisionClient` / `LLMClient` | Statutes, jurisdiction text, a legal fork of this library |
| **Scientific paper example** | IMRaD functions, reporting-guideline and citation-integrity units, peer-reviewer profile | CONSORT/PRISMA/STROBE as Python; a science module |

Scientific paper review is a first-class **example Pack**, not a domain baked
into core. It is also the **testbed** for name → judge → act (same reading
process as a reviewer) before Temida-scale legal packs. Meta:
[`docs/platforms/scientific-paper-review.md`](platforms/scientific-paper-review.md).
Egg fixture: [`examples/papers/egg-low-quality.md`](../examples/papers/egg-low-quality.md).
Sketch: [`examples/scientific_paper_review.py`](../examples/scientific_paper_review.py).
Load the Pack with `Pack.model_validate_json` (or `Pack.model_validate`).
Gaps stay `ontology.function_ids() − covered()` on the host.

## What each object is

| Object | Contains | Does not contain |
| --- | --- | --- |
| `Pack` | Abstract `Ontology` (functions), `SourceUnit`s, `Rule`s | A legal domain, reviewer tone, action policy, pipeline |
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

`missing_elements` is not a ReviewKit field. Gaps are computed on the host
from `covered()`.

## What not to do

- Call `detect()` from host code. It is an internal plant adapter.
- Treat `ReviewFinding.dimension` as a function id.
- Treat `missing_elements` as ontology gaps.
- Fold Pack into `instructions.md`, `external_review_context`, or
  `profile.toml`.
- Expect a fused `complete_json` of findings+actions per sentence.
- Hand-decode Pack JSON into dicts and pass those dicts as the review payload.
- Import a model runtime, weight name, or server URL from `src/reviewkit`.
  Plugins are injected at the call site; tests use mocks only.
- Run `CloseRule` / “missing function X” at sentence scope. Absence is judged
  once, on the document, from `covered()`.

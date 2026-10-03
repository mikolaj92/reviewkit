# ReviewKit

ReviewKit is a domain-agnostic document-review **engine**. 0.24 is a refined
generic review **process** (Pack + two scans + `DecisionClient` /
`LLMClient` sockets). The same engine reviews a privacy notice or a newspaper article; only Pack content changes. A host builds a **Pack** and
injects plugins; ReviewKit does not review domain content itself, does not
encode a statute, and does not ship a model runtime.

```text
document + profile (how) + pack (what)
    → scan 1 name  → scan 2 judge  → optional act
```

Hosts import typed `Pack`, `DecisionClient`, and `LLMClient` objects and pass
instances. JSON files load through `Pack.model_validate` /
`Pack.model_validate_json` only. A review always receives a Pack.

## Roles

| Who | Does | Does not |
| --- | --- | --- |
| Host | Builds Pack, injects `DecisionClient` / `LLMClient`, computes gaps from `covered()` | Expect ReviewKit to know the domain |
| ReviewKit | Two scans, `covered()`, sockets `decide` / `complete_json`, deterministic edits | Import a model runtime; treat `instructions.md` as Pack |
| Pack | Ontology + source units + rules | Behave like a profile |
| Profile | Reviewer behavior (role, language, action policy, pipeline) | Carry acts, ontology, or source units |

## Platforms

ReviewKit is the engine. Domain lives in a host Pack, not in `src/reviewkit`.
The same engine reviews a privacy notice or a newspaper article; only Pack
content changes.

| Surface | What it is |
| --- | --- |
| **Host Pack** | Typed `Pack` / `Ontology` / `Rule` / `SourceUnit` the host constructs in Python, or loads once with `Pack.model_validate_json` at a file edge. Domain names stay in that Pack. |
| **Scientific paper example** | A first-class **example Pack**, not a domain in core. Same engine and ontology *shape* (IMRaD functions); different units and rules. Testbed for name → judge → act. Meta: [`docs/platforms/scientific-paper-review.md`](docs/platforms/scientific-paper-review.md). Pack: [`examples/packs/scientific_paper.json`](examples/packs/scientific_paper.json). Egg fixture: [`examples/papers/egg-low-quality.md`](examples/papers/egg-low-quality.md). Sketch: [`examples/scientific_paper_review.py`](examples/scientific_paper_review.py). Behavior-only profile: [`examples/profiles/scientific.reviewer`](examples/profiles/scientific.reviewer). |

Do not grow this library into a journal or a legal product. Composition is host + Pack.

## Host integration

Construct a Pack as a typed object, inject a `DecisionClient`, run the two scans.
Gaps are `ontology.function_ids() − covered()` on the host — not
`missing_elements`, and not `ReviewFinding.dimension`.

```python
from pathlib import Path

from reviewkit import (
    Function,
    MockDecisionClient,
    MockLLMClient,
    Ontology,
    Pack,
    Rule,
    SourceUnit,
    TaktReviewer,
    TextDocumentParser,
    load_profile,
    parse_text,
    review_document,
    review_source,
    review_tree,
)

pack = Pack(
    ontology=Ontology(functions=[Function(id="opening", label="Opening", attach_to=["sentence"])]),
    units={
        "unit-opening": SourceUnit(
            id="unit-opening",
            source_id="host",
            locator="§1",
            text="Stories open.",
            force="binding",
        )
    },
    rules=[
        Rule(
            id="defect-opening",
            kind="defect",
            function_id="opening",
            scope="fragment",
            when="function_present",
            source_unit_id="unit-opening",
        )
    ],
)
# File edge only:
# pack = Pack.model_validate_json(Path("examples/packs/story.json").read_text())
profile = load_profile("examples/profiles/story.teacher")
llm = MockLLMClient()  # host plugin: LLMClient.complete_json
decision = MockDecisionClient()  # host plugin: DecisionClient.decide

document = parse_text("Once upon a time there was a storm.")

# Format-neutral tree already in memory (no file I/O, no DOCX render):
result = review_tree(document, profile, llm, pack, decision)

# Inject a parser adapter, then review the resulting tree:
result = review_source(
    "Once upon a time there was a storm.",
    TextDocumentParser(source_name="story.md"),
    profile,
    llm,
    pack,
    decision,
)

# DOCX artifacts (reviewed / corrected / JSON report):
result = review_document(
    input_path="input.docx",
    profile_path=profile,
    llm=llm,
    pack=pack,
    decision=decision,
)

# When the host needs the tag map / gaps:
findings, actions, state = TaktReviewer(
    profile=profile,
    llm=llm,
    pack=pack,
    decision=decision,
).review(document)
gaps = pack.ontology.function_ids() - set(state.covered())
```

A runnable copy of this sketch lives at
[`examples/host_pack_review.py`](examples/host_pack_review.py). The longer
contract is [`docs/host-integration.md`](docs/host-integration.md).

A Pack review **requires** `pack=` and `decision=`. Core does not call a
detector as a public host API (`detect()` is internal). Naming returns tags
only (`NamingResponse`); those tags are not `RawSignal`s and are not
`ReviewFinding.dimension`.

## Pack

`Pack` is abstract: `ontology` (functions) + `rules` + `units`. It is not a
legal domain, not `profile.toml`, not `instructions.md`, and not
`external_review_context`.

- `Ontology.functions` — dictionary (`Function.id` / `label` / `attach_to`).
- `SourceUnit.force` — data (`binding`, `dead`, …), not a profile flag.
- Unified `Rule`: `kind` (`label` \| `close` \| `defect`), `scope`
  (`fragment` \| `document`), `when` (`always` \| `function_present` \|
  `function_absent`), optional `source_unit_id`.
- Validators: `function_id` belongs to the ontology; `source_unit_id` belongs
  to `units`. Close is document-scope; label and defect are fragment-scope.

## Two-scan review

1. **Name** every sentence, paragraph, section, and document through
   `DecisionClient.decide` (one noul per function). Tags only — no findings,
   no actions.
2. **Judge** matching `when` rules and the one cited `SourceUnit`. Close /
   `function_absent` runs only on the document, and only when
   `ReviewState.covered()` has no nodes for that function.
3. **Act** through `LLMClient.complete_json` only for `change` / `delete` /
   `insert` above the profile confidence floor. Otherwise a person.

The effector materializes scan-2 actions only. Hierarchical scan order is
still `sentence → paragraph → section → document` (powered by the generic
`takt` cascade). Control flow (cascaded regulation, homeostats, entropy
reduction via splot, vertical waves) is provided by `takt`. ReviewKit supplies
the document plant, Pack/plugin orchestration, and deterministic effectors.

Callers may set `passes` (default `1`) on `review_tree`, `review_source`,
`review_document`, and `TaktReviewer.review`. Pass 1 is the walk above: each
unit is judged on its own text, without comment text from a smaller unit.
Further passes re-judge with comments and labels already produced on the unit
and on the smaller units it contains. Earlier discoveries stay in the result.

## Plugin sockets

Hosts implement these Protocols from `reviewkit`. There is no public `detect()`
API; naming and judging go through `DecisionClient.decide`.

```python
from collections.abc import Mapping
from typing import Protocol

from pydantic import BaseModel

from reviewkit import DecisionState, LLMCapabilities, LLMRequestOptions, Question

# state is DecisionState = str | FragmentDecisionState | DocumentDecisionState


class DecisionClient(Protocol):
    def decide(
        self,
        state: DecisionState,
        questions: Mapping[str, Question],
    ): ...


class LLMClient(Protocol):
    @property
    def capabilities(self) -> LLMCapabilities: ...

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
        *,
        options: LLMRequestOptions | None = None,
    ) -> BaseModel: ...
```

`capabilities` is declared by the host client; ReviewKit does not infer it
from a model name. `complete_json` accepts optional `LLMRequestOptions`
(deadline, token bounds, temperature). The engine currently calls
`complete_json(messages, schema)` without `options`.

Call site: `review_tree(document, profile, llm, pack, decision)`,
`review_source(source, parser, profile, llm, pack, decision)`, or
`review_document(...)`. The CLI is `reviewkit input.docx --profile DIR
--pack FILE --decision module:factory --llm module:factory`. Tests and
examples use `MockDecisionClient` and `MockLLMClient` only. Model runtimes
stay in the host; they are not imported from `src/reviewkit`.

## Profile (behavior only)

Profiles are folders. They do **not** substitute for a Pack. Markdown next to
`profile.toml` is reviewer behavior the host may edit, not ontology or source
units.

```text
examples/profiles/story.teacher/
  profile.toml
  instructions.md
  examples.md
```

```toml
name = "story.teacher"
language = "pl"
document_type = "opowiadanie ucznia"
reviewer_role = "nauczyciel języka polskiego"
review_pipeline = ["sentence", "paragraph", "section", "document"]

[action_policy]
require_llm_apply_hint = true
min_confidence_for_auto_apply = 0.85
max_severity_for_auto_apply = "medium"

[action_policy.apply_policy]
typo = "apply"
grammar = "apply"

[outputs]
reviewed_docx = true
corrected_docx = true
```

`outputs` toggles which DOCX artifacts the pipeline renders. Both default to
`true`. The skipped artifact's path is `None` on the `ReviewResult`. The JSON
report (via `result.save_json(...)`) is unaffected.

The default action policy does not silently rewrite text. A write action must
be allowed by policy, carry enough confidence, have an explicit apply hint,
pass protected-pattern checks, and avoid sensitive-looking text changes unless
the profile opts in.

## Install and Run

```bash
# Supported platform: macOS on Apple silicon (osx-arm64)
curl -fsSL https://pixi.sh/install.sh | sh  # skip if Pixi is already installed
pixi global install -c https://conda.modular.com/max -c conda-forge \
  mojo==1.0.0
mojo --version

uv sync
uv run python examples/host_pack_review.py
uv run reviewkit input.docx \
  --profile examples/profiles/story.teacher \
  --pack examples/packs/story.json \
  --decision my_package.clients:make_decision \
  --out-reviewed reviewed.docx \
  --out-corrected corrected.docx \
  --out-report review-report.json \
  --llm my_package.clients:make_client
```

The CLI requires `--pack`, `--decision`, and `--llm`. Pack JSON is loaded with
`Pack.model_validate_json`. There is no default model client.

`--out-report PATH` writes the JSON report. `--llm module:factory` and
`--decision module:factory` name zero-argument callables that return an
`LLMClient` and a `DecisionClient`.

ReviewKit 0.14+ uses the pinned **takt v0.3.2** in-process Mojo binding.
Requires Python >= 3.13, macOS on Apple silicon, and Mojo `1.0.0`. `uv sync`
installs the Python packages only; the first review compiles and caches Takt's
native module.

The upstream Takt v0.3.2 manifest supports `osx-arm64` only. Install that Mojo
build from Modular's stable Conda channel with Pixi. ReviewKit imports the
pinned `takt` Python package; it does not look for a local source checkout.

The pinned `takt` dependency is the only cascade engine. `TaktClient` calls
its `cascade_step` Python binding in-process and propagates import or
execution failures; there is no subprocess engine or local fallback.

References (same as Fala / Splot):

Marian Mazur, Cybernetyczna teoria układów samodzielnych (1966), Jakościowa
teoria informacji (1970). Józef Kossecki on multi-level autonomous systems
(wielopoziomowe układy samodzielne).
[takt README](https://github.com/mikolaj92/takt) /
[docs/FALA_INTEGRATION.md](https://github.com/mikolaj92/takt/blob/main/docs/FALA_INTEGRATION.md),
[splot docs/CONCEPTUAL_MODEL.md](https://github.com/mikolaj92/splot/blob/main/docs/CONCEPTUAL_MODEL.md),
[Fala docs/CYBERNETIC_MAPPING.md](https://github.com/mikolaj92/Fala/blob/main/docs/CYBERNETIC_MAPPING.md).

## Findings, Actions and JSON Reports

On a Pack review, findings come from scan-2 verdicts (`keep` / `change` /
`delete` / `insert` / `missing`). Function identity lives on the tag
(`FunctionTag.function_ids`) and on `ReviewAction.tags` — not on
`ReviewFinding.dimension`. `ReviewAction` is a possible response: comment,
replacement, insertion, deletion, flag, or advisory action.

`ReviewResult.save_json(path)` writes a report shaped for downstream systems:

- `findings` and `actions` as separate arrays;
- `actions_by_type`, `actions_by_status`, `findings_by_dimension` and
  `findings_by_severity`;
- `applied_actions`, `skipped_actions`, `conflicts` and `needs_human_decision`;
- generated artifact paths and warnings.

## DOCX Rendering

`reviewed.docx` starts from the source DOCX and patches reviewed paragraphs in
place:

- body, table, header and footer paragraphs keep the original document structure;
- text edits are written as native `w:ins` / `w:del` tracked changes;
- review notes are anchored as Word comments on the reviewed fragment when possible;
- `corrected.docx` applies deterministic text-edit actions into a clean document;
- conflicts and hard safety-guard violations are not applied to `corrected.docx`.

Either DOCX render can be turned off per profile via the `outputs` block.

### Revision-aware input

`load_docx()` exposes the document in its effective, post-change view: text
inside `w:ins` is present and text inside `w:del` is omitted from paragraph
text. Original revision evidence remains on
`ReviewDocument.revision_ledger`. Existing Word comments remain in
`document.comments`. Incomplete revision or comment coverage raises
`RevisionCoverageError` before creating an output file.

Rendering a reviewed document preserves source revision wrappers, comment
bodies, and thread sidecars, then adds new review markup with the reviewer
identity and collision-free revision IDs.

`attribute_docx_changes()` recognizes current and hash-bound historical action
comments. It still requires exact action payloads, document hashes, physical
anchors, and unique matches before assigning provenance.

## Extension Points

Domain logic belongs in the host Pack and plugins, not in the framework.

- per-document-type `action_policy` / `action_policies` in profile TOML;
- policy reasons, source-system tags, evidence refs and references on
  `ReviewAction`;
- protected-pattern guards for corrected output safety;
- `ReviewContextProvider` for host grounding on prompts that still accept it.
  It is not a Pack;
- an injectable `ActionPolicy` passed to
  `review_document(..., action_policy=...)`.

## Limitations

- ReviewKit does not decide whether an edit is legally, medically or
  contractually correct, and it does not encode a domain statute.
- ReviewKit does not require or bundle a model runtime.
- Corrected output is deterministic text editing, not a whole-document rewrite.
- Ambiguous edits, stale locators and sensitive-looking replacements are
  blocked for human review unless a profile explicitly relaxes the policy.

## Contributors

- [mikolaj92](https://github.com/mikolaj92)
- [PSyron](https://github.com/PSyron)

## License

ReviewKit is released under the MIT License. See [LICENSE](LICENSE).

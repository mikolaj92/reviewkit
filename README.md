# ReviewKit

ReviewKit is a domain-agnostic Python framework for document review.
It is not a legal checker, grammar checker or one-shot document correction tool.
Applications provide review profiles, LLM clients and optional context; ReviewKit validates
the resulting findings/actions and applies only safe deterministic edits.

It reviews documents in layers (powered by the generic `takt` cascade engine):

```text
sentence -> paragraph -> section -> document
```

The control flow (cascaded regulation, homeostats, entropy reduction via splot, vertical waves) is provided by `takt`. ReviewKit supplies the document plant, LLM detectors, and deterministic effectors.

It can produce three outputs:

- `reviewed.docx` with every correction, suggestion, question and risk marked for human review.
- `corrected.docx` as a clean fully corrected document with text edits applied and no review markers.
- a JSON report with findings, actions, statuses, policy reasons and aggregate metrics.

## Principles

1. The LLM is replaceable.
2. Profiles are YAML/Markdown folders and can define arbitrary review dimensions.
3. Review is hierarchical, not one-shot.
4. Findings describe observations; actions describe what might be done about them.
5. The library validates and applies actions deterministically.
6. Auto-apply is conservative by default and ambiguous edits become conflicts.
7. DOCX and JSON reports are first-class outputs.

## Architecture

ReviewKit 0.13+ is built on the **takt 0.2.0 Mojo-only** cascade regulation engine and re-uses the same Polish cybernetic terminology and structure as Fala and Splot (Marian Mazur, Józef Kossecki).

Takt 0.2.0 ships **no Python runtime**. ReviewKit is the host:

- builds the document plant and runs LLM detectors
- sends `plant_nodes` + `layers` + `raw_signals` over the JSON boundary
- maps `actuation` / `interlock` / `stable` back to `ReviewAction` status

Default engine is a **local 0.2.0-compatible** fusion/homeostat (no Mojo required for tests). To use the real Mojo step:

```bash
export TAKT_HOME=/path/to/takt   # git clone --branch v0.2.0 https://github.com/mikolaj92/takt.git
export REVIEWKIT_TAKT_ENGINE=mojo
```

How ReviewKit maps onto the archetype:

- `ReviewDocumentPlant` + `DocNode` — host plant over sentence/paragraph/section/document (post-order scan).
- `RawSignal` — LLM finding/action candidate → deviation + confidence (+ evidence on the host).
- `LayerSpec` — per-scope homeostat thresholds derived from profile action policy.
- `TaktClient.evaluate` — fusion + homeostat (Mojo `takt_step.sh` or local fallback).
- Actuation → `ReviewAction` status `APPLIED` (subject to post-policy).
- SafetyInterlock → `NEEDS_HUMAN_DECISION` / `CONFLICT`.
- Post-processing (overlap demotion, protected patterns, tracked-revision safety) stays in ReviewKit.

Flow (one document):

- `ReviewDocumentPlant` yields nodes in post-order (deepest first).
- Scope-matched `BaseLLMDetector` produces `RawSignal`s from LLM responses.
- `TaktClient` decides actuation vs interlock vs stable.
- `ReviewEffector` turns the decision + stored LLM response into `ReviewAction`s.
- Deterministic post-pass preserves the public output contract.

Public models (`ReviewFinding`, `ReviewAction`, `ReviewResult`), profiles, `review_document`, and CLI are unchanged.

Requires Python >= 3.13. Optional: Mojo toolchain + takt v0.2.0 checkout for the real cascade step.

References (same as Fala / Splot):

Marian Mazur, Cybernetyczna teoria układów samodzielnych (1966), Jakościowa teoria informacji (1970).
Józef Kossecki on multi-level autonomous systems (wielopoziomowe układy samodzielne).
takt README / docs/FALA_INTEGRATION.md, splot CONCEPTUAL_MODEL.md, Fala CYBERNETIC_MAPPING.md.
## Install and Run

```bash
uv sync
uv run reviewkit input.docx \
  --profile examples/profiles/story.teacher \
  --out-reviewed reviewed.docx \
  --out-corrected corrected.docx \
  --out-report review-report.json \
  --llm my_package.clients:make_client
```

`--out-report PATH` writes the JSON report (the third first-class output). Omit it to skip
the report.

`--llm module:factory` names a zero-argument callable (dotted `module:factory` path) that
returns an `LLMClient`; ReviewKit imports it and calls it to build the client. When omitted,
the CLI falls back to the built-in `MockLLMClient`, because ReviewKit does not assume a
provider. Production integrations pass their own `LLMClient` factory this way.

## Python API

```python
from reviewkit import review_document
from reviewkit.llm import MockLLMClient

result = review_document(
    input_path="input.docx",
    profile_path="examples/profiles/story.teacher",
    llm=MockLLMClient(),
    out_reviewed="reviewed.docx",
    out_corrected="corrected.docx",
)

result.save_json("review-report.json")

for finding in result.findings:
    print(finding.finding_id, finding.dimension, finding.title)

for action in result.actions:
    print(action.action_id, action.status, action.policy_reason)
```

## LLM Interface

```python
from typing import Protocol
from pydantic import BaseModel


class LLMClient(Protocol):
    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: type[BaseModel],
    ) -> BaseModel:
        ...
```

## Review Profiles

Profiles are folders, not Python objects:

```text
profiles/employment-contract.lawyer/
  profile.yaml
  instructions.md
  required-clauses.md
  risky-clauses.md
```

`profile.yaml` defines role, language, document type, pipeline, dimensions and action policy.
Markdown files contain reviewer instructions that can be edited by domain experts.

Profiles are intentionally generic:

```yaml
profile_id: internal-policy-review
name: internal-policy-review
display_name: Internal policy review
language: en
document_type: policy memo
reviewer_role: compliance reviewer
review_dimensions:
  - clarity
  - id: internal_policy
    label: Internal policy
    metadata:
      owner: ops
review_instructions: |
  Review only against the caller-provided criteria.
action_policy:
  apply_policy:
    typo: apply
  require_llm_apply_hint: true
  min_confidence_for_auto_apply: 0.85
  max_severity_for_auto_apply: medium
outputs:
  reviewed_docx: true
  corrected_docx: true
```

`outputs` toggles which DOCX artifacts the pipeline renders. Both default to `true`; set
either to `false` to skip that render (for example a review-only profile that emits a
`reviewed.docx` but never a `corrected.docx`). The skipped artifact's path is `None` on the
`ReviewResult` and absent from its `artifacts` map; the JSON report (via
`result.save_json(...)`) is unaffected.

The default action policy does not silently rewrite text. A write action must be allowed by
policy, carry enough confidence, have an explicit apply hint, pass protected-pattern checks
and avoid sensitive-looking text changes unless the profile opts in. Stale locators and
non-unique text matches are reported as conflicts instead of being applied.

## Findings, Actions and JSON Reports

`ReviewFinding` captures what the reviewer observed: dimension, severity, evidence and
rationale. `ReviewAction` captures a possible response: comment, replacement, insertion,
deletion, flag or domain-specific advisory action. Actions may reference findings with
`finding_id`, but the two are serialized separately.

`ReviewResult.save_json(path)` writes a report shaped for downstream systems:

- `findings` and `actions` as separate arrays;
- `actions_by_type`, `actions_by_status`, `findings_by_dimension` and `findings_by_severity`;
- `applied_actions`, `skipped_actions`, `conflicts` and `needs_human_decision`
  (the fail-closed escalation queue of actions handed to a human);
- generated artifact paths and warnings.

## DOCX Rendering

`reviewed.docx` starts from the source DOCX and patches reviewed paragraphs in place:

- body, table, header and footer paragraphs keep the original document structure;
- text edits are written as native `w:ins` / `w:del` tracked changes around the changed text;
- review notes are anchored as Word comments on the reviewed fragment when possible.
- `corrected.docx` applies deterministic text-edit actions into a clean document.
- Conflicts and hard safety-guard violations are not applied to `corrected.docx`.

Either DOCX render can be turned off per profile via the `outputs` block (see
[Review Profiles](#review-profiles)); a disabled artifact is skipped and its `ReviewResult`
path is `None`.

## Anchored Paragraph Insertion

Besides in-place rendering, ReviewKit ships a standalone insertion engine
(`reviewkit.insertions`, `reviewkit.anchors`) for pipelines that add whole paragraphs —
fix clauses or `[SUGGESTION: ...]` markers — into an existing DOCX at `body:p:<n>` /
`body:p:last` anchors:

```python
from reviewkit import ParagraphInserter, InsertionAction, InsertionValidator

inserter = ParagraphInserter(document, signature_keywords=("signed", "signature*"))
report = inserter.apply_actions([
    InsertionAction(action_id="a1", anchor="body:p:4", text="New clause."),
    InsertionAction(action_id="a2", anchor="body:p:last", text="Wording.",
                    kind="suggest", reason="Missing clause"),
])
```

Placement is deterministic: all anchors resolve against the pristine document before any
mutation, actions sharing an anchor chain in batch order, a paragraph directly followed by
a table keeps its table (insertions land after it), and end-of-document insertions stay
above a trailing signature block. Signature detection and contextual `body:p:last`
re-anchoring are injectable (`signature_keywords`, `resolve_last_anchor`) — the engine has
no built-in language or domain assumptions. `InsertionValidator` re-checks a saved document:
each action's text is where its `applied_anchor` claims, nothing landed below the signature
block, and the body structure is intact.

## Extension Points

ReviewKit keeps domain logic outside the core. Legal, editorial, educational or internal
policy behavior belongs in profiles, context providers or adapters, not in the framework.
Existing extension points include:

- per-document-type `action_policy` / `action_policies` in profile YAML,
- policy reasons, source-system tags, evidence refs and references on `ReviewAction`,
- protected-pattern guards for corrected output safety,
- `ReviewContextProvider` for grounding, classifier results or external evidence,
- an injectable `ActionPolicy` (peer of `ReviewContextProvider`) passed to
  `review_document(..., action_policy=...)`, carrying programmatic
  `PolicyGuard` callables — `(action, node_text) -> reason | None` — for fail-closed rules that
  regex config cannot express.

## Limitations

- ReviewKit does not decide whether an edit is legally, medically or contractually correct.
- ReviewKit does not require or bundle a single LLM provider.
- Corrected output is deterministic text editing, not a whole-document rewrite.
- Ambiguous edits, stale locators and sensitive-looking replacements are blocked for human
  review unless a profile explicitly relaxes the policy.

## Contributors

- [mikolaj92](https://github.com/mikolaj92)
- [PSyron](https://github.com/PSyron)

## License

ReviewKit is released under the MIT License. See [LICENSE](LICENSE).

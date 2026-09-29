# Decide vs fused pass: `DecisionClient.decide` versus `LLMClient.complete_json`

Research note for ReviewKit hosts. This is not a product spec and does not
change the public engine contract. It compares two inference shapes for the
same public objects — `ReviewFinding` (observation) and `ReviewAction`
(possible response) — and when each shape invents edits or loses the span
that justified the rewrite.

## 1. Claim

ReviewKit already **serializes** findings and actions as separate arrays
(`README`: “Actions may reference findings with `finding_id`, but the two
are serialized separately”). The **model call** does not. Today every
scope detector asks one `LLMClient.complete_json` for a `ReviewResponse`
that contains both `findings[]` and `actions[]`, including
`original_text` / `replacement_text`. That fused decode is the **legacy
path: pack = None**.

A split path would:

1. Run `DecisionClient.decide` for **name + judge** (short, low-entropy
   answers: dimension, presence/absence, severity, confidence, apply vs
   comment vs human).
2. Run `LLMClient.complete_json` only for **act text** (quote-grounded
   replacement, insertion, or comment body), given a packed decision.

The split wins when the fused decode invents a rewrite in order to
justify a finding. The fused path wins when the pack dropped the quote,
locator, or evidence that the rewrite must copy. Neither path decides
legal or scientific correctness; ReviewKit still only validates and
applies locators deterministically.

## 2. Two inference shapes

```text
FUSED (legacy, pack=None)
  fragment + profile + schema(ReviewResponse)
        │
        ▼
  LLMClient.complete_json  →  findings[] AND actions[]
        │
        ▼
  detectors → RawSignal(finding) + RawSignal(action)
        │
        ▼
  takt fusion / homeostat → actuation | interlock | stable
        │
        ▼
  ReviewEffector materializes stored actions
        │
        ▼
  prepare_actions / ActionPolicy  (post-hoc gates)

SPLIT
  fragment + profile
        │
        ▼
  DecisionClient.decide  →  name + judge  (short)
        │
        ▼
  pack = {finding_id, node_id, original_text, dimension,
          disposition, evidence, locator?}
        │
        ▼
  LLMClient.complete_json(act schema)  →  replacement / comment
        │
        ▼
  same takt / effector / policy as above
```

`pack = None` means: there is no decision envelope to hand a generator.
The host therefore asks one model to emit the whole `ReviewResponse`.
That is ReviewKit 0.23 as shipped.

### 2.1 What `decide` is allowed to say

Name and judge are **classification-shaped**:

| Field | Role | Entropy |
| --- | --- | --- |
| `name` | dimension / issue type (`clarity`, `missing-clause`, `overclaim`, …) | closed or small open set |
| `judge` | disposition: none / comment / rewrite / human; severity; confidence | few bits |
| `evidence` | quote or `EvidenceRef`, not a new clause | copy, not invent |

`decide` must not emit `replacement_text`. A short answer that already
contains a redline is a fused pass wearing a judge badge.

### 2.2 What `complete_json` is allowed to say on the split path

Act text only: `original_text` (must match the pack quote),
`replacement_text` or `comment_text`, optional locator fill-in.
The generator does not re-name the finding and does not re-judge
severity. If the quote is gone from the current node, the host fails
closed (`prepare_actions` already escalates stale locators to
`CONFLICT`).

### 2.3 What ReviewKit already does instead of a second model

The prompt in `prompts.py` tells the model to “Return findings
separately from actions” **inside one JSON object**. Detectors then
emit two `RawSignal` families from that one payload
(`llm_*.finding` and `llm_*.action`). Takt fuses them. `ReviewEffector`
replays the **stored** fused response. `ActionPolicy.decide` and
`prepare_actions` run **after** generation.

So the engine already splits **objects** and **regulation**. It does
not split **generation**. Policy can refuse to apply a hallucinated
edit; it cannot un-invent the tokens.

## 3. Literature and practice (mapped onto the two shapes)

These citations are engineering analogues, not ReviewKit dependencies.

### 3.1 Classifier → generator pipelines

Production contract stacks classify clause type (NLI / Legal-BERT /
DeBERTa, CUAD-style taxonomies) **before** an LLM drafts a redline
against a playbook. Scientific claim verification (SciFact: Wadden et
al., 2020) is retrieve → SUPPORTS / REFUTES / NOT ENOUGH INFO →
rationale span. Cite-checking systems (CiteTracer, citecheck) extract
and **judge** a reference, then propose a field-level repair only
when the matcher has a grounded record.

The shared pattern: the generator is not allowed to choose the class.
If class and rewrite share one decode, the rewrite pulls the class
along (“I wrote a governing-law clause, therefore governing law was
missing”).

### 3.2 Judge models

LLM-as-judge surveys (Li et al., 2024, *From Generation to Judgment*;
Gu et al., 2024) treat judging as a **different task** from generation:
short labels, rubrics, pairwise preference. Judges are biased and
need grounding (no-free-labels work; reference answers help). That
matches a `DecisionClient` that returns name+judge, not a second
full `ReviewResponse`.

LegalHalluLens (2026) goes further: **typed** hallucination profiles
on CUAD (numeric, temporal, obligation/entitlement, factual) and a
Risk Direction Index for omission vs invention. Aggregate “52%
hallucination” hides a 38–40 pp gap between obligation/numeric and
temporal claims. A fused pass that also writes `replacement_text`
mixes those types in one object; a decide pass can refuse rewrite
on obligation/numeric while still commenting on temporal drift.

Dahl et al., *Large Legal Fictions* (2024): public LLMs hallucinate
on ≥58% of verifiable legal questions and poorly predict their own
errors. Magesh et al. (2024): even RAG legal-research tools still
hallucinate 17–33% of the time. Neither result is about ReviewKit,
but both say: **do not let the same decode that is bad at law also
author the redline**.

### 3.3 Reward models

Lightman et al., *Let’s Verify Step by Step* (2023): process
supervision (a label per step) beats outcome supervision on MATH.
Fused `complete_json` is outcome-shaped: one JSON blob scored as a
whole. Split decide→act is process-shaped: a judge score on name+
disposition, then a separate score on quote-faithful act text.
Outcome reward on a fused blob can reinforce “fluent JSON that
contains an action” even when the finding is false.

### 3.4 Tool use

ReAct / function-calling practice: the model **selects** a tool
(name) then **fills** arguments (act). `LLMCapabilities.supports_tools`
already exists on the ReviewKit client protocol and is unused by
detectors. A host could expose `decide` and `propose_edit` as tools
and still land in the same public `ReviewFinding` / `ReviewAction`
models. That is composition at the host, not a new engine.

Tool use is not free: the model can skip the judge tool and jump to
`propose_edit`. The host must **require** a pack (or pack=`None`
fused fallback), not hope the model calls tools in order.

### 3.5 Structured-output entropy

Constrained decoding makes schema validity ~100% and does **not**
make content true (arxiv:2609.23742: CD rescues form; instruction-
semantic failures remain). The “constraint tax” (arxiv:2605.26128):
hard schemas on small models raise validity while **lowering**
answer accuracy and inflating wrong-but-valid outputs. Farquhar et
al., *Nature* 2024: confabulations show up as high **semantic**
entropy (meaning-level disagreement), not as invalid JSON.

Implications for ReviewKit:

- `ReviewResponse` is a **wide** schema: findings, actions, summary,
  risks, questions, missing_elements, human_decisions,
  reconciliation_requests. Filling it in one decode maximizes
  tokens that can be fluent and false.
- Name+judge is a **narrow** schema (enum + few floats). Lower
  output entropy, better calibrated abstention, cheaper to
  constrain.
- Act `complete_json` is still generative and high-entropy, but the
  search space is “rewrite this quote,” not “invent a review.”
- Schema-valid `replacement_text` is the dangerous case: policy
  sees a well-typed action; `prepare_actions` only checks that
  `original_text` occurs in the node, not that the replacement
  preserves legal or scientific meaning.

Takt already treats residual entropy as a fusion/homeostat signal
(`LayerSpec.entropy_threshold`, `ErrorSignal.residual_entropy`).
That entropy is over **host-supplied scalars**, not over JSON
tokens. A fused pass that emits both a confident finding and a
confident action looks like agreement to fusion even when both
are the same confabulation. Split lets the host feed a high-confidence
judge and a separately estimated act uncertainty.

## 4. Mazur / Kossecki as engineering analogy only

Not a scientific claim about documents. A vocabulary already used
by Takt, Splot, and Fala for **organ boundaries**.

Mazur’s autonomous system (*Cybernetyczna teoria układów
samodzielnych*, 1966) separates:

- **receptor** — take information from the environment
- **correlator** — store and transform it
- **homeostat** — oppose flows that reduce the system’s ability to act
- **effector** — act on the environment

Qualitative information theory (*Jakościowa teoria informacji*,
1970) treats information as a **transformation between communicates**,
not Shannon bits. Splot’s conceptual model already uses that:
many high-entropy communicates in, one lower-entropy commitment
out. Kossecki’s wielopoziomowe układy samodzielne is the
multi-level part: each layer has its own homeostat; higher layers
constrain lower ones (Takt’s sentence → paragraph → section →
document cascade).

Mapped onto this note:

| Organ | Fused pass | Split pass |
| --- | --- | --- |
| Receptor | one LLM sees the fragment | same, or a cheaper classifier |
| Correlator | findings **and** redline in one communicate | `decide` produce a short communicate (name+judge) |
| Homeostat | takt + `ActionPolicy` after the fact | can interlock **before** act tokens exist |
| Effector | Docxtor still applies text | same, but act JSON is the only generative effector input |

Fusing diagnosis and redline is one communicate that is too large
for the homeostat to regulate: the correlator has already written
the effector’s output. Splitting is two communicates with a
named contract between them (the pack). That matches Fala’s rule:
named conduction between effectors, not a shared blob.

Kossecki’s levels are **already** the review pipeline. Adding
decide vs act **inside** a layer is another level of specialization,
not a second cascade engine. ReviewKit should not grow a product
orchestrator to host it; a Fala journal with two effectors
(`decide`, `act`) plus the existing takt reviewer is the
composition boundary (`AGENTS.md`).

## 5. When the fused path hallucinates edits

Mechanism: next-token generation is jointly optimizing “sound like
a reviewer” and “emit a complete `ReviewResponse`.” Empty
`actions[]` looks like a failed review. The schema and the prompt
both invite an action per finding (`finding_id` on both). The
decode therefore **invents treatment**.

`prepare_actions` catches **anchor** failures (missing
`original_text`, non-unique match, opaque overlap, protected
pattern change). It does not catch a unique, well-quoted span
whose `replacement_text` changes meaning. That is the fused
hallucination that reaches `corrected.docx` when policy auto-applies.

### 5.1 Legal document QA

Worked from the employment-contract profile
(`examples/profiles/employment-contract.lawyer`): flag ambiguous
wording, missing clauses, risky formulations, inconsistent
definitions, one-sided terms — **without** changing legal sense
unless marked as a human decision.

| Failure | What the fused decode does | Why split would have stopped it |
| --- | --- | --- |
| Invented missing clause | `missing_elements` plus `INSERT_*` of a stock governing-law / non-compete paragraph | `decide` can say `name=missing-clause`, `judge=human` without drafting statute-shaped prose |
| Silent meaning change | `REPLACE` on a real quote: “may”→“shall”, “reasonable” deleted, indemnity cap removed | judge = `rewrite` only for playbook-allowed classes; obligation/numeric types stay comment (LegalHalluLens direction) |
| Playbook ventriloquism | replacement copied from instructions.md, not from the contract | act pass still can do this, but only after name+judge; host can retrieve clause-library text **into** the pack |
| Locator laundering | fabricated `original_text` that almost matches, unique enough to apply | decide must copy a quote; act is forbidden to change it |
| Absence on incomplete source | document-level “no limitation of liability” + insert, while `source_document.complete` is false | ReviewKit already forbids document-wide absence without complete source; fused still **writes** the insert in the same object. Split can skip act when judge is `unsupported-absence` |

LegalHalluLens’ omission vs invention index matters here: fused
generation is biased toward **invention** (an action is a thing to
emit). Decide can return `none` / `comment` as first-class short
answers.

### 5.2 Scientific document QA

The conformance corpus `paper` case is the local fixture: n=12
samples, conclusion claims population effectiveness. A correct
finding is “overclaim.” A fused action that “fixes” the conclusion
by inserting a p-value, a larger n, or a citation is a scientific
hallucination **even if** the finding title is right.

| Failure | Fused decode | Split |
| --- | --- | --- |
| Number repair | “12” → “120” or invented CI / p | judge `overclaim` → act is a hedge (“in this sample”), not a new statistic |
| Citation insert | `INSERT` of Author (2024) to “support” the claim | decide never emits a reference; act only if pack includes a retrieved record (citecheck-style) |
| Unit / direction flip | SciFact-style: *higher* vs *lower* troponin still schema-valid | name=`direction-error` with quoted span; act must keep numerals from the pack |
| Table/figure blindness | fragment text lacks the table; model invents the missing cell | judge `not-enough-info` / `human`; no act |
| Hedge deletion | replace “suggests” with “demonstrates” while “fixing” grammar | name=`overclaim` should block apply_hint |

SciFact labels are SUPPORTS / REFUTES / NEI plus a rationale span.
That is decide-shaped. Drafting a corrected sentence is a different
task, and mixing them produces “verified” text that was never in
the abstract.

## 6. When the split path loses context between tag and rewrite

Mechanism: two calls, two contexts. Anything not in the pack is
invisible to act. The generator then re-reads the fragment (or
worse, only the tag) and writes a fluent edit for a **nearby**
span.

### 6.1 Legal

| Failure | What was lost | Symptom |
| --- | --- | --- |
| Tag without quote | `name=ambiguous-termination`, no `original_text` | act rewrites the compensation clause in the same paragraph |
| Coarse name | `name=clarity` | generic paraphrase that shifts burden of proof |
| Disposition without locus | `judge=rewrite`, `node_id` = section | act picks the first sentence; `prepare_actions` may still apply at paragraph grain |
| Playbook id dropped | decide knew “use clause L-14”; pack has only the name | act invents L-14 from memory |
| Cross-definition | decide flagged defined term “Confidential Information”; pack omitted the definition sentence | act “fixes” a use site and desyncs the definition |
| Human bit dropped | judge=`human` not packed | act still emits `apply_hint=true` |

### 6.2 Scientific

| Failure | What was lost | Symptom |
| --- | --- | --- |
| Claim without measurement | `name=overclaim` | act hedges a different sentence than the one with n=12 |
| Span not packed | rationale was “całej populacji”; act only sees “skuteczności” | rewrite changes the wrong noun |
| Table pointer dropped | judge used a number from a table not in `current_fragment` | act invents the number from parametric memory |
| Polarity | REFUTES vs SUPPORTS not packed | act “corrects” a true statement |
| Unit | decide saw “12 próbek”; pack says `name=sample-size` | act writes “12 patients” |

The fused path avoids these because the same decode still has the
fragment in context when it writes `replacement_text`. That is the
real advantage of pack=`None`: **one attention span** over quote
and rewrite. It is also why fused hallucinations are coherent
(finding title, reason, and redline agree with each other, not
with the world).

## 7. Pack contract (the actual difference)

Split is safer than fused **if and only if** the pack is a
complete, host-owned communicate. Minimum fields:

1. `finding_id` — stable; act must copy, not mint.
2. `node_id` + review scope — where Takt already ran.
3. `original_text` — verbatim substring of current node text
   (the same string `prepare_actions` will match).
4. `name` / dimension — closed vocabulary from the profile.
5. `judge` — `{disposition, severity, confidence, apply_hint allowed?}`.
6. `evidence` — quotes / `EvidenceRef`s that decide used.
7. Optional `locator` if decide had exact coordinates; else omit
   (do not guess).

If any of (1)–(6) is missing, **pack = None**: fused
`complete_json(ReviewResponse)` remains the honest fallback.
A half-pack is worse than fused: it looks split while acting
like an ungrounded generator.

Host-owned audit fields (`lineage`, `status`, `policy_reason`)
stay off the model schema (`model_boundary.strip_model_audit_fields`).
The pack is semantic context, not an audit replica.

## 8. Recommendation for this repo

ReviewKit should stay the document plant, validators, and
effectors. Do not fold `DecisionClient` into `detectors.py` as a
second god-path.

Practical order:

1. **Keep fused `complete_json(ReviewResponse)`** as the protocol
   default (`pack is None`). Hosts and tests already speak it.
2. **If a host has a DecisionClient**, compose **outside** the
   engine (Fala effectors, or a thin adapter that turns packs into
   `ReviewFinding`s plus a narrower act schema). Feed the existing
   `ReviewContextProvider` with classifier/judge output — that
   extension point already exists.
3. **Do not generate act text until** disposition is `rewrite` or
   `comment`. `none` / `human` / `unsupported-absence` skip
   `complete_json`.
4. **Never let act re-judge.** Confidence and `apply_hint` on the
   writing action are copied from the pack or stripped to policy
   defaults.
5. **Keep `prepare_actions` and protected patterns** on both
   paths. Split reduces invented meaning; it does not replace
   locator uniqueness, opaque-content demotion, or sensitive-text
   guards.
6. **Measure separately** for legal and scientific profiles:
   invented-edit rate (fused failure) vs off-span rewrite rate
   (split failure). Typed legal categories (obligation vs
   temporal) and SciFact-style NEI vs REFUTES should not be
   averaged.

A fused pass that hallucinates edits is a correlator writing the
effector’s output. A split pass that loses the pack is an
effector acting on a nameless impulse. The homeostat in between
is the pack, not another LLM call.

## 9. References

Code in this tree: `src/reviewkit/llm.py`, `detectors.py`,
`prompts.py`, `models.py` (`ReviewResponse`), `effectors.py`,
`takt_reviewer.py`, `policy.py`, `action_prepare.py`,
`model_boundary.py`, `homeostat.py`; `examples/profiles/employment-contract.lawyer/`;
`tests/test_conformance_corpus.py`.

Sibling organs: Takt conceptual model (fusion / homeostat /
entropy threshold); Splot conceptual model (high-entropy
communicates → one commitment); Fala cybernetic mapping
(receptor / correlator / homeostat / effector; named conduction).

External (accessed 2026-09-29):

- Wadden et al., *Fact or Fiction: Verifying Scientific Claims* (SciFact), ACL 2020. <https://huggingface.co/papers/2004.14974>
- Lightman et al., *Let’s Verify Step by Step*, 2023. <https://arxiv.org/abs/2305.20050>
- Dahl, Magesh, Suzgun, Ho, *Large Legal Fictions*, J. Legal Analysis, 2024. <https://huggingface.co/papers/2401.01301>
- Magesh et al., *Hallucination-Free? Assessing the Reliability of Leading AI Legal Research Tools*, 2024. <https://huggingface.co/papers/2405.20362>
- Farquhar et al., *Detecting hallucinations in large language models using semantic entropy*, Nature 2024.
- Li et al., *From Generation to Judgment: Opportunities and Challenges of LLM-as-a-judge*, 2024. <https://huggingface.co/papers/2411.16594>
- Gu et al., *LLMs-as-Judges: A Comprehensive Survey*, 2024. <https://huggingface.co/papers/2412.05579>
- *The Constraint Tax: Measuring Validity-Correctness Tradeoffs in Structured Outputs*, 2026. <https://arxiv.org/html/2605.26128>
- *Constrained Decoding Eliminates Structural Failures in Small LLMs but Reveals a Scale-Dependent Semantic Gap*, 2026. <https://arxiv.org/abs/2609.23742>
- LegalHalluLens, *Typed Hallucination Auditing…*, 2026. <https://huggingface.co/papers/2606.18021>
- Marian Mazur, *Cybernetyczna teoria układów samodzielnych* (1966); *Jakościowa teoria informacji* (1970).
- Józef Kossecki on multi-level autonomous systems (wielopoziomowe układy samodzielne).

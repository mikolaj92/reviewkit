# Three transitions `name → judge → act` vs two scans + optional act

Research note for ReviewKit 0.24 Pack reviews and the Temida host.
Not a host-integration contract; the shipped contract is
[`docs/host-integration.md`](../host-integration.md).

**Question.** Is Pack review a three-takt cascade (`name → judge → act`), or
is that a Mazur-style description of three *transitions* while the product is
two plant scans plus an optional write effector?

**Answer, up front.** Keep the implementation. Tighten the messaging.

- `name` and `judge` are plant **scans**. Only `judge` is a **takt** (it is
  the only Pack path that calls `takt.cascade_step`).
- `act` is a gated **effector fill** after the homeostat has already spoken.
  It is not a third `sequential_scan` and not a third cascade evaluate.
- Optional `act` means the live product is two-pass for most nodes.
- Temida should keep a cheap decision plugin (Basal) on
  `DecisionClient.decide` for both scans, and a generative plugin (Qwen) on
  `LLMClient.complete_json` only for high-confidence `change` / `delete` /
  `insert`. Do not force `act`. Do not merge `judge` into `act`.

The three *transitions* remain a valid information-theory story. Calling them
three *tacts* of the cascade organ is the error.

---

## 1. Vocabulary (the actual disagreement)

Four words are being used as if they were one clock.

| Word | Meaning here | Who owns it |
| --- | --- | --- |
| **Takt** | One cascade evaluate: plant node + `RawSignal`s → fusion → homeostat → `actuation` / `interlock` / `stable`. Canonical loop in takt `docs/CONCEPTUAL_MODEL.md`. | Takt Mojo binding |
| **Scan** | One walk of `ReviewDocumentPlant.sequential_scan()` (post-order: sentence → paragraph → section → document). | ReviewKit host |
| **Transition** | A Mazur-style transform of a communicate (text → tags, tags+rules → verdict, verdict → replacement). | Conceptual, not an API |
| **Pass** | Prompt/payload label (`action_prompt` stamps `"pass": "action"`). Historical “three-pass” wording in the 0.24 commit. | Prompt envelope |

Takt’s own job statement is:

> Stabilize hierarchical state, tact by tact, under descending constraints
> and ascending telemetry — fail closed when fusion cannot reduce entropy.

A tact in that document is collect → fuse → homeostat → wave. It is not “any
LLM call” and not “any phase of a product.” Fala’s mapping agrees: a
**homeostat** is defensive regulation; an **effector** is the operational
edge that leaves a **reaction** in the world
([`Fala` `docs/CYBERNETIC_MAPPING.md`](https://github.com/mikolaj92/Fala/blob/main/docs/CYBERNETIC_MAPPING.md)).

If those four words collapse, three different claims become indistinguishable:

1. Pack review has three *information* stages (true).
2. Pack review walks the plant three times (false).
3. Pack review runs `cascade_step` three times per node (false).

The rest of this note keeps them apart.

---

## 2. What 0.24 actually runs

Pack path, from `TaktReviewer.review`:

1. `_name(plant)` — first `sequential_scan`. `DecisionClient.decide` with one
   noul per ontology function. Tags only. No cascade. No effector.
2. Second `sequential_scan`. `judge()` → findings → `RawSignal`s. Empty
   signal lists **continue** (no evaluate, no act). Otherwise
   `takt_client.evaluate`, then `act_after_judge`, then
   `effector.apply_takt_decision`.
3. `act_after_judge` calls `LLMClient.complete_json` only for
   `change` / `delete` / `insert` at or above
   `min_confidence_for_auto_apply`. `missing` is a finding. Below the floor
   the action goes to a person with no replacement text. Plugin failure
   degrades to a person (`act_plugin_failed`), it does not fail the review.

Order on a node that actually reaches takt:

```text
judge → RawSignal → cascade_step → TaktDecision
      → act_after_judge (maybe complete_json)
      → ReviewEffector.apply_takt_decision(already-computed decision)
```

Replacement text is generated **after** the homeostat decision and **does
not** re-enter `raw_signals`. The cascade cannot see the write. That is the
hardest single fact against “act is a third takt.”

Shipped host copy already says two scans:

```text
Pack load  →  inject DecisionClient  →  two scans (name, then judge)
                                         → optional LLMClient act
```

Tension in the tree, which is why this note exists:

| Surface | Wording |
| --- | --- |
| `docs/host-integration.md`, README diagram, CHANGELOG 0.24.0 | two scans + optional write |
| README / CHANGELOG section “Two-scan review” | numbered 1 name, 2 judge, **3 Act** |
| `action_prompt` docstring | “Pass 3” |
| 0.24 landing commit | “three-pass Pack review” |
| `TaktReviewer` module docstring | 1 name, 2 judge, 3 optional act — and name “No cascade, no effector” |

Tests lock the two-scan reading, not the three-takt reading:

- `test_empty_rules_pack_names_and_skips_judge_takt_and_act` — name only;
  zero takt; zero `LLMClient`.
- `test_name_does_not_register_with_the_effector` — name is not a reaction.
- `test_two_scans_name_before_takt_and_keep_tags_off_raw_signals` — four
  `decide` calls before the first `evaluate`; tags never become `RawSignal`.
- `test_missing_does_not_call_the_act_plugin` —
  `VerdictKind.MISSING` is not a write.
- `test_act_skipped_below_confidence_does_not_call_llm` — floor gates Qwen.
- `test_act_runs_only_for_change_above_confidence` — the only path that
  stamps `"pass": "action"`.
- `test_pack_review_calls_llm_only_to_act` — `LLMClient` is not a judge.

`pack=None` is a different product: one fused `complete_json` per node, and
empty signals still evaluate. Do not use that path as evidence for Pack
clocking.

Temida’s source is not readable from this checkout (private). Host-wiring
claims below are taken from ReviewKit sockets, the CHANGELOG ban on importing
Basal / Qwen / Jev / vLLM into core, and `docs/host-integration.md` naming
Temida as the Pack host.

---

## 3. Steelman: three transitions `name → judge → act`

The strongest version of the claim is not “three `cascade_step`s.” It is:

> A Pack review is three distinct transforms of a communicate, with three
> output types, two plugin sockets, and three fail-closed stories. Collapsing
> the third into “optional” hides that `corrected.docx` exists only because
> act exists.

### 3.1 Three communicates, not one fused JSON

Pre-0.24 fused `*ReviewResponse` (findings **and** actions in one
`complete_json`). Pack 0.24 split that on purpose:

| Stage | Input | Output | Socket |
| --- | --- | --- | --- |
| Name | fragment text | `FunctionTag`s (`NamingResponse`) | `DecisionClient.decide` (noul) |
| Judge | tags + matching `Rule` + one `SourceUnit` | `Verdict` → `ReviewFinding` → `RawSignal` | `DecisionClient.decide` (choice / present) |
| Act | verdict + cited unit + fragment | `ActionText.replacement_text` | `LLMClient.complete_json` |

Mazur’s qualitative information theory treats information as a
**transformation between communicates**, not as a Shannon bit count (Splot
`docs/CONCEPTUAL_MODEL.md` restates this for fusion). Name, judge, and act
are three such transforms. Calling the product “two scans” can be read as
denying the third transform.

### 3.2 Different organs in the Fala/Mazur mapping

Fala’s lexicon maps the three stages onto **different organs**, which is
exactly why a host might still say “three transitions”:

| Stage | Fala / Mazur organ | Why it is not the others |
| --- | --- | --- |
| Name | Association (registration of a reading) | Tags are coverage for `covered()`, not aberration |
| Judge | Homeostat (defensive regulation) | `keep` / `change` / `delete` / `insert` / `missing`; only this stage feeds takt |
| Act | Effector → Reaction (footprint in the document) | Replacement text, tracked `w:ins`/`w:del`, `corrected.docx` |

On that reading, “optional act” is like saying “optional effector.” An
autonomous system without effectors is a correlator that never touches the
world. ReviewKit’s public contract still promises a corrected artifact. The
third transition is product-shaped even when most nodes skip the LLM.

### 3.3 Two sockets are the point of 0.24

`DecisionClient` is forbidden from naming-or-judging through
`complete_json` on a Pack path; `LLMClient` is forbidden from naming or
judging. That split is the whole 0.24 plugin story. A host that budgets
**three** model roles (or two roles with act gated) is not confused: it is
matching the sockets. “Two scans” describes plant walks. “Three transitions”
describes plugins and output types. Both can be true.

### 3.4 Analog: detect / decide / repair is a common product spine

Grammar, SAST, medical coding, and journals all *talk* in three moves even
when the third is gated (survey in §7). A reviewer saying “name, judge,
rewrite” is speaking that dialect. Shipping docs that number Act as step 3
under a “Two-scan review” heading is the same dialect leaking into the
README.

### 3.5 What the steelman does *not* require

It does not require:

- a third `sequential_scan`;
- `act` to produce `RawSignal`;
- `act` to run on `keep` / `missing`;
- Basal to generate prose, or Qwen to answer noul questions.

Those would be a different claim: **force three tacts**. The steelman is
only: do not pretend the write is conceptually the same thing as “post
processing after judge.”

---

## 4. Attack: act is not a third takt, and optional means most nodes are 2-pass

### 4.1 Takt’s definition excludes name and act

Inside Takt: raw signals → `ErrorSignal` → homeostat. Empty raw list is
stable (aberration 0). Host builds the plant and maps actuation back.

Pack `name`:

- does not emit `RawSignal` (tags are not a field on `RawSignal`; tests
  forbid stuffing them into `evidence`);
- does not call `evaluate`;
- does not register with `ReviewEffector`.

Pack `act`:

- does not emit `RawSignal`;
- does not call `evaluate`;
- runs only after a non-empty judge signal list (the `continue` in the
  judge loop);
- mutates `response.actions` that the effector then stamps with the
  **already computed** `TaktDecision`.

Only `judge` is a tact of the cascade. Name is a scan. Act is an effector
hook. Counting LLM calls as tacts would also make `pack=None` “one takt per
node,” which is true only coincidentally: that path *does* evaluate every
node, Pack judge does not.

### 4.2 Optional is not a marketing hedge; it is the control flow

`act` is skipped when:

| Condition | Test / code |
| --- | --- |
| No matching rules (empty pack, untagged fragment, covered close) | `judge_rules` returns `[]` → `continue` before evaluate |
| All verdicts `keep` | `_verdicts` drops `KEEP` → empty signals → `continue` |
| Verdict is `missing` | `_ACT_KINDS` is change/delete/insert only |
| Confidence below profile floor | `requires_human_decision`, no `complete_json` |
| `LLMClient` throws | degrade to person, review continues |

So “optional act” is not “scan 3 that often no-ops after walking the plant.”
There is no third plant walk. For a node that stays `keep`, the host paid
name (always) + maybe judge (if a defect rule matched) + **zero** generative
calls.

On a long contract that is the common case. Ontology naming hits every
enabled non-empty node. Fragment judge hits tagged nodes with
`function_present` defect rules. Writes hit a subset of those with high
confidence `change`/`delete`/`insert`. Document-scope `close` /
`function_absent` is once per missing function, and never writes.

Empirically: **the product is two-pass for most nodes**, and one-pass
(name only) for untagged / unmatched nodes. That is what
`test_empty_rules_pack_names_and_skips_judge_takt_and_act` encodes.

### 4.3 Calling act a takt would lie to the homeostat

If act were a third cascade tact, replacement text (or a write-confidence
signal) would have to re-enter fusion. It does not. Takt decides from judge
findings alone. A fluent but unlawful rewrite cannot raise entropy; a clumsy
but policy-correct rewrite cannot lower it. Post-policy in ReviewKit
(`prepare_actions`, overlap demotion, protected patterns) is a **second**
host-side homeostat, still not a takt of the write model.

That is fail-closed in the right place: the cheap classifier decides
*whether* to touch the world; the generator only fills the payload; the
deterministic applier decides *whether the payload is admissible*.

### 4.4 “Three-pass” oversells Qwen occupancy

If Temida plans GPU / latency / money as “three model steps × N nodes,” it
will provision a generative model on every sentence. The tests say that is
wrong. The honest capacity model is:

```text
name:  O(nodes × |ontology|) DecisionClient calls
judge: O(matched rules)      DecisionClient calls
act:   O(high-confidence writes) LLMClient calls, often ≪ nodes
takt:  O(nodes with non-keep findings) cascade_step calls
```

Name is the expensive *decision* scan. Act is a rare *generative* spike.
Those must not share a utilization story.

### 4.5 README already admits the effector truth

> The effector materializes scan-2 actions only.

Act attaches actions onto the judge response. The effector does not see a
scan-3 object. The cascade does not see a scan-3 signal. The only consumer
of `LLMClient` on the Pack path is `_replacement_text`. That is an effector
adapter with an LLM behind it, not a third regulator.

---

## 5. Is act a true third takt, or an effector after judge?

**Effector after judge.** Criteria used:

1. **Clock.** A takt is one `cascade_step` on a plant node. Act never
   calls it.
2. **Plant.** A scan is one `sequential_scan`. Act has none; it is
   `act_after_judge` inside the judge loop.
3. **Information into the regulator.** Act’s output is not a `RawSignal`.
4. **Fail-closed story.** Judge failure is `ReviewBoundError` (stops the
   node). Act failure is a person (`NEEDS_HUMAN_DECISION` / no text).
   Different organs have different failure modes; Fala distinguishes
   effector blame from correlator blame for the same reason.
5. **Mazur/Fala names.** Homeostat vs effector is the native vocabulary.
   Reusing “takt” for both erases that cut.

Act *is* a true **third transition** (verdict → replacement). The
recommended sentence is:

> Two scans (name, judge). One takt (judge). One optional write effector
> (act). Three transitions of the communicate.

---

## 6. Temida host wiring: Basal on decide, Qwen on act

Core does not import Basal, Qwen, Jev, vLLM, URLs, or weight names
(CHANGELOG 0.24.0; `tests/test_docs_pack_canon.py` keeps those names out of
examples). The sockets are the wiring diagram.

| Socket | Pack job | Model class Temida should bind |
| --- | --- | --- |
| `DecisionClient.decide` | Name (noul per function) and judge (`keep`/`change`/`delete`, or document `present`) | Basal — small decision / classifier. Bounded answers, confidence, reason. No prose rewrite. |
| `LLMClient.complete_json` | Replacement text for gated writes | Qwen — generative, schema `ActionText`. Called only after judge already chose a write kind. |

Implications:

1. **Do not put Qwen on `DecisionClient`.** Name is `O(nodes × functions)`.
   A generative model answering hundreds of noul questions will dominate
   cost, inject style into tags, and blur `covered()`. Basal’s job is
   sitko: which functions are on this fragment.
2. **Do not put Basal on `LLMClient`.** `action_prompt` asks for replacement
   text constrained by one verdict and one unit. A decision model will
   under-generate or echo the source. That is Qwen’s job, and it is
   *allowed* to be expensive because it is rare.
3. **The optional gate is what makes the split affordable.** Force-act
   (next section) would drag Qwen onto `keep` nodes and destroy the
   Basal/Qwen economics.
4. **Merge judge+act** would force one plugin to both classify and write,
   which is the fused `pack=None` path 0.24 demoted to legacy. Temida would
   either run Qwen as a judge (cost) or Basal as a writer (quality).
5. **Takt stays in-process Mojo.** Neither Basal nor Qwen is the cascade.
   Host wiring of models must not be mistaken for cascade layering.
   ReviewKit still maps judge findings to `RawSignal` and lets takt choose
   actuation vs interlock vs stable; Qwen does not vote in that homeostat.
6. **Human floor is a third “model.”** Below `min_confidence_for_auto_apply`,
   Temida must show a person the verdict *without* a Qwen draft (current
   behavior: `replacement_text is None`). Generating a draft anyway is a
   product choice; it is not “making act a takt.” If Temida wants drafts
   for humans, that is a fourth, display-only call, still not cascade.

Dike remains the document-review rendering/engine consumer of ReviewKit.
Argus/Temida orchestration stays out of this library (`AGENTS.md`). This
note only constrains how Temida should bind the two sockets ReviewKit
already exposes.

---

## 7. Analogous pipelines

Same pattern repeats: a cheap/closed detect-or-name pass, a judge pass that
*is* the product, and a gated generate/apply that is a different organ.

### 7.1 Grammar checkers — tag → match → optional apply

LanguageTool is the cleanest analog.

- **Name / tag.** POS and other tags are a separate output (`tags.txt` vs
  `results.txt` on the CLI). Tagging is not the correction.
- **Judge.** `POST /check` returns `matches[]`: rule id, message, offset,
  and a list of `replacements`. Detection and *suggested* repair travel
  together, like ReviewKit judge findings plus a *template* replacement —
  still not a second model.
- **Act.** `--apply` / `applyCorrection` is an **optional effector**. Docs
  tell you to enable only rules reliable enough to auto-correct, apply the
  first suggestion, and re-run if a later rule should see the new text.
  Apply is not a third linguistic analysis; it is a DOM/text write.

Grammarly-class products add a generative “rewrite the paragraph” card.
That card is optional, billed/gated, and not the underline pass. Shipping
it as “the third takt of grammar” would be the same category error as
calling Pack `act` a takt.

**Lesson.** Suggestions may be computed *with* the match (cheap, closed)
or by a later generator (expensive, optional). ReviewKit chose the latter
for Pack writes. Do not pretend that makes apply a third scan of the tree.

### 7.2 CodeQL — query → alert → optional autofix

GitHub code scanning:

- **Find.** CodeQL queries over a database. Deterministic, suite-scoped.
- **Judge.** An alert with location, severity, rule. This is the product
  users triage. Enabling CodeQL is enough to get alerts.
- **Fix.** Copilot Autofix translates an alert into a suggested patch with
  a **different** model (docs: GPT-5.3-Codex as of 2026). Agentic autofix
  is a further optional cloud-agent loop that re-runs CodeQL to *validate*
  the patch. Neither is “query evaluation takt 3.” Autofix can be disabled
  at org/repo level; the scanner still ships.

**Lesson.** Find and fix use different engines. Fix is optional, separately
policy-gated, and (in the agentic variant) *re-enters* the finder as
verification. ReviewKit deliberately does **not** re-enter takt with the
rewrite. If Temida ever wants “Qwen then re-judge,” that would be a new
reconciliation loop, not “act was a takt all along.”

### 7.3 Medical coding — suggest codes → coder justifies → optional query

AHIMA computer-assisted coding (CAC) practice:

- NLP **suggests** ICD/CPT codes from documentation (name/classify).
- A credentialed coder **reviews and verifies** (judge). The coder’s
  attestation is the homeostat; the engine does not bill.
- A **query** to the physician is a separate, compliance-gated act
  (AHIMA/ACDIS query practice: technology-generated queries must still be
  non-leading, cited, not reimbursement-driven). Query is not run on every
  code. LLM-drafted query text is explicitly treated as a query, not as
  the coding pass.

**Lesson.** Generating language (the query, or a rewrite) is the dangerous
step and is optional. Classification + human/homeostat verification is the
spine. Pack `missing` (finding, no write) is closer to “documentation gap /
query candidate” than to `act`.

### 7.4 Peer review — major/minor vs revision

ICMJE: the **editor** is the homeostat; reviewers advise; journals need not
follow reviewer recommendations. Typical editor decisions: accept, minor
revision, major revision, reject (Elsevier Digital Commons and COPE-aligned
journal process docs).

Mapping:

| Peer review | Pack |
| --- | --- |
| Reviewer tags issues (major/minor) | Name + judge (`keep` vs change/delete, `missing`) |
| Editor accept / revise / reject | Takt actuation / interlock / stable + policy floor |
| Author revision | Act — **different agent, later cycle** |
| Major revision → re-review | Reconciliation (`pack=None` today; not Pack act) |

Author rewrite is not the third takt of the referee’s reading. It is an
effector in another being (the author), often followed by a **new** review
scan. Forcing Qwen to rewrite every judged fragment in the same breath as
Basal’s verdict is the equivalent of having the referee silently commit a
new manuscript before the editor has ruled.

Minor vs major is closer to ReviewKit’s confidence floor: minor → auto
write; major → person; reject/`missing` → no write.

### 7.5 Analog summary

| Pipeline | Spine (always) | Gated organ | If you called the gate a third takt you would… |
| --- | --- | --- | --- |
| LanguageTool | tag + match | `--apply` | run apply on every unmatched sentence |
| CodeQL | query + alert | Autofix / agent | spend Codex on every alert, including noise |
| CAC | suggest + coder | physician query / LLM draft | query every chart |
| Journal | review + editor | author revision | rewrite the paper inside the referee report |
| Pack 0.24 | name + judge | `LLMClient` write | call Qwen on `keep`/`missing` |

All four analogs **steelman** three *transitions* and **attack** three
*tacts*. They ship as two-pass products with an optional repair effector.

---

## 8. Options (and when each would be right)

### A. Rename / tighten messaging (recommended)

**What.** Keep the code. Stop saying “three-pass” / “Pass 3” / “step 3 Act”
as if it were a third plant scan or a third `cascade_step`. Canonical line:

> Pack review is two scans (name, then judge) and one optional write
> effector (act). Judge is the only Pack takt. Name, judge, and act remain
> three transitions of the communicate.

Touch README “Two-scan review” numbering, `action_prompt`’s “Pass 3”
docstring, and any host copy that budgets three model steps per node.
Do not change sockets.

**When this is the right move** (all of these hold today):

- Act does not walk the plant and does not call `cascade_step`.
- Host models split classifier vs generator.
- Most nodes must not pay the generator.
- Analog products in §7 ship this way.
- Tests already encode optional act.

### B. Keep as-is (code *and* mixed wording)

**What.** Leave README listing Act as item 3 under “Two-scan review.”

**When.** Never as a stable state. The implementation is already A’s
implementation; only the words drift. Drift is how Temida will over-provision
Qwen. Acceptable only as a freeze if no host is wiring models yet — which
is not the situation described in `docs/host-integration.md`.

### C. Force act always

**What.** Call `complete_json` on every judged node, or on every named
node, including `keep` / `missing` / below-floor.

**When this would be right:**

- A profile whose *job* is to emit a full parallel draft (rewrite-the-doc
  products), not a review.
- Write confidence is *inputs* to the homeostat (you would then need act
  **before** `evaluate`, i.e. a real third tact) — that is a different
  engine.
- Analog: LanguageTool `--apply` on a tiny set of high-precision rules, or
  a “always show a rewrite card” UX that does not auto-apply.

**Why not for Temida/ReviewKit:** contradicts `missing` semantics, the
human floor, CodeQL-style optional autofix, CAC query gating, and Basal
vs Qwen cost. It would also still not be a takt unless signals were
rebuilt from the draft.

### D. Merge judge + act

**What.** One plugin call returns verdict **and** replacement. Collapse
`DecisionClient` and `LLMClient` on the Pack path (return to fused JSON).

**When this would be right:**

- One model is genuinely best at both classification and constrained
  rewrite, and node count is small enough to pay it always.
- Host cannot inject two sockets.
- Analog: LanguageTool match that already carries `replacements[]` from
  the **same** rule engine (closed suggestions, not an LLM).

**Why not for 0.24:** the Pack split exists so Basal can name/judge and
Qwen can write. Merge is `pack=None` with extra ceremony. It also couples
fail-closed (judge bound errors) to degrade-to-person (act plugin failure).

### E. Promote act to a true third takt (not requested, listed for completeness)

**What.** Third `sequential_scan` or a post-judge `evaluate` whose
`raw_signals` include write quality / residual after the draft.

**When:** you need the homeostat to see the rewrite (CodeQL-agentic
“re-run the query”). That is a new loop: judge → act → **re-judge**.
Reconciliation on `pack=None` is the existing sketch of that idea.
Do not sneak it in by renaming `act_after_judge`.

---

## 9. Decision criteria (short)

Use this table; do not pick by taste.

| If this is true | Do |
| --- | --- |
| Act is not `cascade_step` and not a plant walk | Do not call it a takt. **A** |
| Host binds a classifier and a generator to different sockets | Keep sockets split; gate the generator. **A**, not **C**/**D** |
| `keep` / `missing` / low confidence must not write | Keep optional act. Not **C** |
| `corrected.docx` must still exist when writes happen | Keep act as a transition/effector. Not “delete step 3 from the ontology” |
| Replacement quality should affect actuation | New re-judge loop. **E**, not rename |
| One model, small docs, suggestions closed-form | **D** (LanguageTool-like), not Temida’s Basal/Qwen plan |
| Mixed README “two scans” + “3. Act” is confusing hosts | **A** immediately; **B** is the bug |

---

## 10. Conclusion

**Steelman, granted:** `name → judge → act` are three real transitions
(association, homeostat, effector). 0.24’s two sockets exist because those
transitions are different jobs. Analog pipelines speak that way.

**Attack, granted:** they are not three tacts and not three scans. Only
judge is a takt. Act is an effector after the homeostat, gated hard enough
that **most nodes are two-pass or name-only**. Optional is the product, not
a footnote.

**Ship:** keep the implementation (two scans + optional act). **Rename
messaging** so Temida does not wire Qwen as a third cascade step. Bind
Basal to `DecisionClient.decide` (both scans) and Qwen to
`LLMClient.complete_json` (writes only). Do not force act. Do not merge
judge+act unless the host abandons the two-model plan.

Canonical sentence for hosts:

> Load a Pack. Scan once to name. Scan once to judge (that scan is the
> takt). Optionally write through a generative effector. Count GPUs on
> writes, not on nodes.

---

## Sources

### In this repo (0.24 Pack path)

- `src/reviewkit/takt_reviewer.py` — `_name`, `judge`, `act_after_judge`,
  evaluate-then-act order, `continue` on empty signals.
- `src/reviewkit/decision.py` — `DecisionClient` socket; name vs fragment vs
  document state.
- `src/reviewkit/pack.py` — `judge_rules`, `VerdictKind`, `ActionText`.
- `src/reviewkit/prompts.py` — `action_prompt` (`"pass": "action"`).
- `src/reviewkit/effectors.py` — stamps an already-made `TaktDecision`.
- `docs/host-integration.md`, `docs/releases/0.24.0.md`, `CHANGELOG.md`,
  `README.md`.
- Tests: `tests/test_takt_reviewer_pack.py`, `tests/test_pack.py`,
  `tests/test_docs_pack_canon.py`.

### Sibling organs

- [takt `docs/CONCEPTUAL_MODEL.md`](https://github.com/mikolaj92/takt/blob/main/docs/CONCEPTUAL_MODEL.md) — one tact = collect → fuse → homeostat.
- [Fala `docs/CYBERNETIC_MAPPING.md`](https://github.com/mikolaj92/Fala/blob/main/docs/CYBERNETIC_MAPPING.md) — effector vs homeostat vs association.
- [splot `docs/CONCEPTUAL_MODEL.md`](https://github.com/mikolaj92/splot/blob/main/docs/CONCEPTUAL_MODEL.md) — Mazur: information as transform of communicates; host acts *after* fusion.

### Analogs

- LanguageTool: [`/check` match + replacements](https://raw.githubusercontent.com/api-evangelist/languagetool/refs/heads/main/openapi/languagetool-check-api-openapi.yml); [CLI `--apply` and tags vs matches](https://dev.languagetool.org/tips-and-tricks.html); [browser `applyCorrection`](https://deepwiki.com/languagetool-org/languagetool-browser-addon/4.3-dom-interaction-and-correction-application).
- GitHub: [About autofix for code scanning](https://docs.github.com/en/code-security/concepts/code-scanning/autofix-for-code-scanning) (alert vs Copilot Autofix vs agentic re-run).
- AHIMA: [Automated Coding Workflow and CAC Practice Guidance (2013)](https://journal.ahima.org/Portals/0/archives/AHIMA%20files/Automated%20Coding%20Workflow%20and%20CAC%20Practice%20Guidance%20(2013%20update).pdf); [AHIMA/ACDIS query practice (2026)](https://bok.ahima.org/media/zc0bqdjt/2026_acdis-ahima_compliant-query-practice.pdf).
- ICMJE [peer-review responsibilities](https://www.icmje.org/recommendations/browse/roles-and-responsibilities/responsibilities-in-the-submission-and-peer-peview-process.html); Elsevier Digital Commons [editorial decisions (accept / minor / major / reject)](https://digitalcommons.elsevier.com/journal-editorial-process-and-peer-review/editorial-decision-and-revisions).

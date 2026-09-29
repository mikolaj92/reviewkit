# Scientific peer review as Pack

Research note. No engine, API, or profile change. The product Pack JSON, if
any, belongs in [`examples/packs/scientific_paper.json`](../../examples/packs/scientific_paper.json)
(or a host repo) — not in `src/reviewkit`.

**This Pack is the poligon.** A scientific-paper Pack (topic-agnostic IMRaD
jobs + integrity rules + primer units, run on a real manuscript) is the
proving ground that should **reveal the pros, cons, and wrong assumptions**
of the three-pass slogan

```text
name sentence-by-sentence → judge → act/score
```

Law notices and story Packs are too small or too clause-local to falsify
that slogan. A paper is long, hierarchical, absence-critical, ethically
non-writable, and split between checklist completeness and fused merit.
If three-pass is a good control meta, it will show up here. If it is a bad
*execution* meta (three neural calls per sentence, a coverage score as
peer review, the referee as author), it will show up here first. Do not
change the engine to “make the poligon pass.” Change the *reading* of
three-pass, or compose overlays at the host.

**Question.** Can journal-style peer review of a scientific paper be a
ReviewKit Pack — and, in being so, which claims of three-pass survive?

**Verdict.** Yes, for completeness and integrity. No, for merit, novelty,
and importance. The *roles* name / judge / act survive. The naive clock
(name every **sentence**, then judge, then **act or score**) does not.
Shipped 0.24 is two plant scans plus optional write; a journal **score**
(accept / major / reject) is the editor’s homeostat, not pass 3. Temida
loads a different Pack than a legal notice; the sockets stay
`DecisionClient.decide` and optional `LLMClient.complete_json`.

The locked 0.24 contract this note consumes, and does not reopen:

- Pack = `Ontology` + `Rule`s + `SourceUnit`s. Profile is behaviour.
- Scan 1 **name** tags functions. Scan 2 **judge** matching rules. **Act**
  is an optional write after the homeostat.
- Fragment judge: `kind=defect` only. Never `close`. Never
  `when=function_absent`.
- Document judge: `kind=close` / `function_absent` only when
  `ReviewState.covered()` has no nodes for that function.
- Host gaps: `pack.ontology.function_ids() − set(state.covered())`.
- Colloquial **DefectRule** / **CloseRule** in this note mean
  `Rule.kind == "defect"` and `Rule.kind == "close"` on the unified `Rule`
  type (`src/reviewkit/pack.py`). There are no separate classes.

Sibling notes cover the meta; this instance is the poligon that should
make that meta fail in public:

- [`name-judge-act-cross-domain-meta.md`](name-judge-act-cross-domain-meta.md)
  — roles vs fused merit; 3-pass vs fused; failure modes F1–F14
- [`three-takt-vs-two-scan-optional-act.md`](three-takt-vs-two-scan-optional-act.md)
  — scans ≠ tacts; act is not a score; editor vs author rewrite
- [`covered-and-close-scope.md`](covered-and-close-scope.md)
  — document-only close; CONSORT/PRISMA/IMRaD operators
- [`pack-as-game-cross-domain.md`](pack-as-game-cross-domain.md)
  — game vs profile; scholarly checklist encodings
- [`decide-vs-fused-pass.md`](decide-vs-fused-pass.md)
  — scientific QA failure of fused rewrite (invented p / citation)

Artifacts to run the poligon on: §1.5 (example Pack + fixture paper,
linked when present).

---

## 1. Poligon: what three-pass claims, and what a paper Pack can break

The candidate architecture under test is not “does ReviewKit have findings
and actions.” It is this clock, often said in one breath:

| Beat | Naive three-pass (the slogan) | What 0.24 actually runs |
| --- | --- | --- |
| **Name** | Walk **sentence by sentence**. Tag each sentence with ontology functions. | Walk **sentence → paragraph → section → document**. One noul per function on every enabled node (`naming_functions`). Tags only. No cascade. |
| **Judge** | Score or rule-check those sentence tags against the Pack. | Matching `when`/`scope` rules. Fragment: `defect` only. Document: `close` / `function_absent` only if `covered()` is empty for that function. |
| **Act / score** | Rewrite the sentence, or emit a paper-level score (accept / 4.2 / “CONSORT 80%”). | Optional `LLMClient` write for high-confidence `change`/`delete`/`insert` only. `missing` is a finding. A journal decision is **not** a Pack verdict. |

Those two columns are easy to confuse because both have three *words*.
The poligon’s job is to keep them apart on a document where the confusion
is expensive: a scientific paper.

### 1.1 Why this domain, not a notice or a story

[`examples/packs/story.json`](../../examples/packs/story.json) has three
functions; a missing `conflict` is one document close. The notice fixture
[`tests/fixtures/notice.pack.json`](../../tests/fixtures/notice.pack.json)
has two. Neither has (all of):

- a **section-shaped** job (`methods`) that naive sentence-name will either
  spam or miss;
- a **document-shaped** absence (no Methods anywhere) that sentence judge
  will false-positive on every Results sentence;
- a **joint** judge (claim vs evidence) that 1-function rules cannot see;
- an ethical ban on Act (ICMJE/COPE: do not ghostwrite; do not invent
  numbers);
- a second judge that is *not* a Pack at all (novelty / importance);
- overlay checklists (CONSORT/PRISMA/ARRIVE) large enough to hit
  lost-in-the-middle if you stuff them into every sentence prompt.

A paper Pack plus a manuscript is therefore the smallest honest test of
the slogan. Legal Temida Packs remain the other instance of the *same*
engine; they are the wrong poligon for “name every sentence then score.”

### 1.2 Pros the poligon should be able to show (keep these)

If the Pack + fixture are run as 0.24 actually ships them, these should
come out as **advantages of splitting roles**, not of sentence-clocking:

1. **Absence is typed.** Missing Methods is `ontology − covered()`, then
   one document `close`. Fused sentence review cannot see the rest of the
   PDF (#343). That is the steelman of a second scan.
2. **Presence ≠ quality.** Thin Methods is `defect` on a tagged section,
   not a second `missing`. The fused `missing_elements` lie dies in public.
3. **Topic-agnostic ontology.** Graphene and zebrafish share jobs; content
   stays on the document. One Pack identity, many manuscripts.
4. **Overlays compose.** CONSORT/PRISMA/ARRIVE are other Packs, not
   `if rct` in the engine. Version CONSORT 2010 vs 2025 in unit data.
5. **Egg / mill papers fail as data.** Headings without jobs → empty
   `covered()` on `methods`/`evidence`/`citation`; fake references →
   `defect` plus a host sensor. No new `Rule.kind`.
6. **Audit trail.** Finding carries `function_id`; unit carries `url` /
   `locator` (Shannon, Popper, TOP, CONSORT item). A chat instruction
   cannot.
7. **Act can stay off.** Most paper nodes should never call
   `complete_json`. That is a *pro* of optional act, visible only if the
   poligon does not force a score-or-rewrite third beat.

### 1.3 Cons the poligon should be able to show (do not paper over)

1. **Cost if you believe the slogan literally.** Name is
   `O(|nodes| × |functions|)` noul questions, and `naming_functions`
   offers **every** function at sentence, paragraph, section, *and*
   document. A 4k-sentence manuscript × a CONSORT overlay is the F12
   blow-up in the meta note. The poligon should measure this, not assume
   Basal makes it free.
2. **Cascade miss (F1).** Name drops the only Methods paragraph → document
   `close` fires → a naive Act inserts a duplicate methods block the
   author never wrote. Joint IE already knew the first-stage cap.
3. **Cascade hallucination (F2, COBPeer).** Name tags “we randomised
   order of questions” in the Introduction as `randomisation_method` →
   `covered()` suppresses CONSORT close → silent gap. Structured Judge
   also over-calls (COBPeer specificity 61% vs 77%).
4. **Wrong-home witnesses.** Any sentence tag counts for existential
   `covered()`. Located IMRaD (“there is a Methods *section*”) is a
   different operator
   ([`covered-and-close-scope.md`](covered-and-close-scope.md)).
5. **Lost interaction (F7).** `claim` present and `evidence` present
   somewhere is not “this claim is supported.” SciFact is pair-shaped.
   0.24 rules are one function × one unit.
6. **Pack too large (F8).** Dumping CONSORT+PRISMA+ARRIVE+TOP+Popper into
   one Judge prompt reproduces RAPID’s reason for RAG. The poligon
   should prefer a small genre Pack plus overlays, and should fail
   visibly if someone pastes the CONSORT PDF into `instructions.md`.

### 1.4 Wrong assumptions the poligon is for (kill these readings)

These are the slogan’s hidden load-bearing claims. A paper Pack should
**not** be tuned until they look true. They are false.

| # | Assumption in “name sentence-by-sentence → judge → act/score” | Why a scientific paper falsifies it |
| --- | --- | --- |
| A1 | **The sentence is the name grain for every function.** | `methods` / `results` / `discussion` are section jobs. `claim` / `citation` are often sentence jobs. Absence is a document job. One grain is a type error. |
| A2 | **Three plant walks, or three `cascade_step`s, or three LLM calls per sentence.** | 0.24: two `sequential_scan`s; only judge hits takt; act is not a scan. See [`three-takt-vs-two-scan-optional-act.md`](three-takt-vs-two-scan-optional-act.md). |
| A3 | **Pass 3 is a score** (coverage %, CONSORT fraction, accept/reject). | `covered()` is a presence map, not quality and not merit. A paper with every heading tagged can still be a bad idea. NIH already split admin completeness from Factor 1. |
| A4 | **Pass 3 is a rewrite of the manuscript.** | ICMJE/COPE: reviewers advise; authors revise in a *later* cycle. Inventing a p-value or a reference is a scientific hallucination ([`decide-vs-fused-pass.md`](decide-vs-fused-pass.md) §5.2). |
| A5 | **`covered()` cardinality is peer review.** | Extra tags are allowed (SOX redundant controls; PRISMA non-prescriptive location). Close cares about **empty** lists. A 90% tag rate is not an accept. |
| A6 | **Merit is another Pack function** (`novelty`, `importance`). | Those judges do not decompose into named units. Tagging “for the first time” in the abstract will fill `covered()["novelty"]` and lie. |
| A7 | **Sentence `function_absent` finds missing Methods.** | Every Results sentence would close-miss Methods. That is the bug 0.24 just named. Missing Methods = document `close` after scan 1. |
| A8 | **Name is frozen before Judge.** | A playbook/CONSORT violation can tell you the span was mis-tagged. Without reconciliation (#312) the pipeline cannot recover. |
| A9 | **Headings instantiate functions.** | Egg papers have IMRaD outline and no methods job. Name must tag the job, not the outline string. |
| A10 | **One Pack for reporting *and* journal score.** | Completeness Pack + fused qualitative + editor homeostat. Collapsing them is how a CONSORT-complete worthless trial looks “accepted.” |

A1–A10 are why this note exists as a **poligon**, not as a product spec
for a third cascade organ. The engine stays. The slogan gets a smaller
mouth: three *transitions* of a communicate, two *scans*, optional
*write*, host *score*.

### 1.5 Artifacts: example Pack + fixture paper (cross-link when present)

Run the poligon on a **Pack instance** plus a **manuscript**, not on this
markdown. Do not add either file in a research-only change. When they
exist, they are the object under test; this note’s function ids in §3.2
are sketches.

| Artifact | Path | In tree on this branch? | Role in the poligon |
| --- | --- | --- | --- |
| Scientific paper Pack | [`examples/packs/scientific_paper.json`](../../examples/packs/scientific_paper.json) | **No** (sibling platform PR; link is the landing path) | Genre ontology + `defect`/`close` + primer units. Prefer IMRaD + claim/evidence/citation, not a CONSORT dump. |
| Story Pack (stand-in) | [`examples/packs/story.json`](../../examples/packs/story.json) | **Yes** | Same schema, smaller game. Document `close` on uncovered `conflict` is the Methods-gap shape. |
| Legal notice fixture | [`tests/fixtures/notice.pack.json`](../../tests/fixtures/notice.pack.json) | **Yes** | Temida-shaped thin double. Contrast instance, not the poligon manuscript. |
| Fixture paper (corpus) | [`tests/test_conformance_corpus.py`](../../tests/test_conformance_corpus.py) — case `"paper"` | **Yes** | Two-sentence overclaim (`n=12` → population). Enough to show fused Act hallucination; **not** enough to show sentence-name cost or missing-Methods close. |
| Host sketch | [`examples/host_pack_review.py`](../../examples/host_pack_review.py) | **Yes** | How gaps are computed: `ontology.function_ids() − set(state.covered())`. |
| Manuscript fixture (platform) | `tests/fixtures/` or `examples/` when the platform PR lands a paper file | **No** | Needed to exercise IMRaD close, egg headings, fake references. Until then the corpus `"paper"` case is the only in-tree manuscript. |

If `examples/packs/scientific_paper.json` is present in the revision you
are reading, treat it as the product instance and ignore conflicting
illustrative ids below. If a dedicated manuscript fixture is present,
that file — not the two-sentence corpus string — is the poligon input.
Wire them with `review_tree(..., pack=..., decision=...)` as in
[`docs/host-integration.md`](../host-integration.md). Measure, at least:

- noul count vs sentence count vs function count (A2, cost);
- whether `methods` close fires once at document, never per sentence (A7);
- whether a heading-only IMRaD shell leaves `methods` in `gaps` (A9);
- whether Act is skipped on `missing` / `keep` (A4);
- that no score field is written from `|covered| / |ontology|` (A3, A5).

---

## 2. How peer review actually works

Peer review is not one LLM pass over a PDF. It is a staged control process
with several roles, several decision vocabularies, and several checklists
that already look like Packs. ICMJE and COPE are explicit that **reviewers
advise and editors decide**; authors revise. ReviewKit must not collapse
those three agents into one `complete_json`.

### 2.1 Roles

| Role | Job in the journal | Pack analogue |
| --- | --- | --- |
| Managing / technical editor | Files, ethics statements, word limits, similarity, required headings | Deterministic Name of completeness units; some Close |
| Handling editor (desk) | Scope, fatal methods, “is this even a paper of this journal” | Cheap Name + fused qualitative; often no Act |
| External reviewer | Claims vs evidence, methods adequacy, reporting, literature | Name + Pack Judge; Act = comments |
| Statistical / reporting reviewer | CONSORT/PRISMA/ARRIVE/STROBE item status, stats consistency | Overlay Pack Judge (`defect` / `close`) |
| Editor-in-chief / handling homeostat | Accept, minor, major, reject | Takt + policy; not a third model rewrite |
| Author | Revision under editor constraints | Act in a *later* cycle, different agent |

COPE ethical guidelines for peer reviewers forbid ghostwriting the
manuscript. ICMJE restricts AI-assisted review. That is Act polymorphism:
the scientific default is **comment**, not `replacement_text`. The legal
Temida Pack may redline from approved language; a paper Pack that auto-inserts
a p-value or a citation is a scientific hallucination
([`decide-vs-fused-pass.md`](decide-vs-fused-pass.md) §5.2).

### 2.2 Decisions

Typical editorial outcomes (Elsevier / Springer / COPE-aligned process
docs): desk reject, reject after review, major revision, minor revision,
accept. Mapping onto Pack verdicts is many-to-one and must stay on the
**host**:

| Editor decision | What the Pack may have shown | What ReviewKit must not do |
| --- | --- | --- |
| Desk reject (not a paper / out of scope) | Empty `covered()` on `research_question` or `methods`; or host scope filter | Invent a methods section |
| Reject after review | Many `missing` closes + high-severity `defect`s | Rewrite results so the defects vanish |
| Major revision | `close` on required functions and/or `defect` on present ones | Treat Qwen draft as the revision |
| Minor revision | Local `defect`s, `covered()` complete | Auto-apply only reporting boilerplate, if the profile allows |
| Accept | Judge `keep` on named functions; gaps empty | Claim the engine “accepted” the science |

Minor vs major is closer to the profile confidence floor than to a new
`Rule.kind`. Reject / `missing` is a finding, not a write
(`docs/host-integration.md`).

### 2.3 Checklists as ontology / rules patterns

EQUATOR reporting guidelines are the scholarly form of a Pack. They do not
generate manuscript text. They name items, state where a reader might look,
and distinguish “not reported” from “reported badly.”

| Guideline | Document it governs | Pack pattern |
| --- | --- | --- |
| **CONSORT 2025** (30 items + expanded bullets) | Randomised trial *report* | Functions = items; E&E bullets = `defect` criterion; most items = document `close`; title identifier = located completeness (host filter on `covered()`, not fragment close) |
| **PRISMA 2020** (27 items + flow + abstract checklist) | Systematic review | Same; location is a template, not a prescription (PRISMA E&E). Flow diagram is a *form* of a function |
| **ARRIVE 2.0** | Animal research | Methods-floor overlay (SciScore already names organisms, randomisation, blinding, sample size) |
| **STROBE** | Observational studies | Overlay on the same IMRaD base Pack |
| **SPIRIT 2025** | Trial *protocol* (different artifact) | Different Pack identity, not a flag on the paper Pack |
| **MDAR** | Life-science methods resources | Resource/RRID functions + `defect` |
| **TOP guidelines** | Transparency/openness levels | `data_availability`, `code`, `preregistration` as functions; journal TOP level as unit `force` |
| **ICMJE** | Authorship, COI, overlapping publication | Completeness functions (`competing_interests`, `author_contributions`) |
| **COPE** | Integrity process | Rarely a function; more often host routing (plagiarism sensor → editor) |

The pattern that repeats, and that ReviewKit already implements:

```text
Function     = a namable job or reporting item
SourceUnit   = the item text + E&E / primer (one locator, one force)
label        = always, fragment          # scan 1
defect       = function_present, fragment  # present but bad
close        = function_absent, document   # never named anywhere
```

COBPeer (Chauvin et al., *BMC Medicine* 2019) is the empirical warning:
a CONSORT-structured Judge raises recall of incomplete reporting (86% vs
20%) and drops specificity (61% vs 77%). A scientific Pack will over-call.
That is a host calibration problem, not a reason to stuff CONSORT into
`instructions.md`.

Study-design checklists are **overlays**, not the base ontology. A sociology
survey and an RCT share IMRaD jobs; only the RCT loads CONSORT. Host
composition (multiple Packs, optional nested Fala journals) is how you stack
them. One mega-Pack that is CONSORT + PRISMA + ARRIVE + STROBE + ICMJE is
the “Pack too large / lost in the middle” failure in the meta note.

---

## 3. Why a topic-agnostic ontology works

The usual objection: “physics is not psychology; you cannot have one paper
Pack.” That objection confuses **content** (data on the document) with
**structure** (jobs the document must perform). Peer review already treats
them differently. Reviewers in every empirical field ask the same four
questions IMRaD encodes: what is the question, how did you look, what did
you find, what does it mean (CASRAI IMRaD Structure; Sollaci & Pereira,
*CMAJ* 2004, on IMRaD’s 20th-century takeover of original articles).

### 3.1 Stable jobs, variable payload

| Stable (ontology) | Variable (document data, not Pack data) |
| --- | --- |
| There is a research question | The question is about graphene / voting / zebrafish |
| There is a method that could be assessed | NMR protocol vs survey instrument vs RCT |
| There are results | Spectra, coefficients, Kaplan–Meier curves |
| There is a discussion against prior work | Which papers, which theory |
| Claims are posed as at-risk statements | The particular hypothesis |
| Evidence is cited and located | The particular figure, table, or reference |
| Limitations are stated | Which threats to validity |
| Open-science artefacts are pointed to | Which repository, which TOP level the journal demands |

A Pack that encodes graphene or zebrafish has become a domain dump
([`pack-as-game-cross-domain.md`](pack-as-game-cross-domain.md) §7.2). A Pack
that encodes `methods`, `claim`, `evidence`, `citation`, `limitations` can
review both papers with the same `judge_rules`. The DecisionClient still
*reads* the chemistry; it does not need chemistry *functions*.

This is the same split as the notice fixture: `controller_identity` and
`purposes` are jobs of a privacy notice, not a dump of the company’s
processing activities. The activities are in the document. The jobs are in
the ontology.

### 3.2 What the base paper ontology is (research sketch)

Illustrative ids only. Product ids live in
[`examples/packs/scientific_paper.json`](../../examples/packs/scientific_paper.json)
when that file is present; this note must not fork a second JSON. The shape
is the story Pack’s shape (`opening` / `conflict` / `resolution` in
[`examples/packs/story.json`](../../examples/packs/story.json)): genre jobs,
not topic keywords. Mixed `attach_to` is poligon A1: one grain is a type
error.

```text
# Genre (IMRaD + front/back matter)
title
abstract
research_question      # Introduction’s job
methods
results
discussion
limitations            # often a job inside Discussion; venue-dependent close

# Argument (topic-agnostic)
claim
evidence
citation

# Integrity / openness (journal-conditional close)
data_availability
code_availability
preregistration
competing_interests
author_contributions
```

`attach_to` is documentation of the usual home (`section` for IMRaD jobs,
`sentence` for `claim` / `citation`). Naming still offers every function at
every scope (`naming_functions`). `covered()` counts a tag on any node.
Hosts that need “Methods is a *section*” filter the tag map by plant
identity — they do not run `function_absent` on every Results sentence
([`covered-and-close-scope.md`](covered-and-close-scope.md) §5, §12).

### 3.3 Overlays stay overlays

When scan 1 has tagged `methods` *and* the host knows the study design
(RCT, systematic review, animal experiment), load a second Pack:

| Design signal | Overlay Pack | Extra functions (examples) |
| --- | --- | --- |
| “randomised trial” in title/methods | CONSORT 2025 | `randomisation_method`, `blinding`, `participant_flow`, `outcomes_and_estimation` |
| “systematic review” | PRISMA 2020 | `eligibility_criteria`, `information_sources`, `study_selection`, `flow_diagram` |
| vertebrate animal work | ARRIVE 2.0 | `sample_size_justification`, `experimental_animals`, `housing_and_husbandry` |
| observational health | STROBE | `setting`, `participants`, `bias`, `study_size` |

The overlay is how SciScore (MDAR/ARRIVE floor) and Penelope (per-journal
heading/ethics catalogue) already compose in the wild. They do not merge
into one prompt. ReviewKit should not either.

### 3.4 What topic-agnostic does *not* buy

Merit, novelty, and “is this important?” are not functions. NIH Factor 1
Importance and journal novelty are fused qualitative judges. A Pack that
adds `novelty` so that `covered()` can be checked will tag every abstract
that says “for the first time” and call the paper complete. That is theatre
(meta note §4.2, domain matrix “Scientific papers, merit”).

The `#314` corpus already knew this: the `paper` case is one engine, a
profile that talks about method and evidence, and a finding that the
conclusion overclaims a sample of 12. The *shape* is domain-neutral. The
*criterion* is Pack/profile data. Do not grow `if scientific` in
`src/reviewkit`.

---

## 4. Mapping onto name → judge → act and `covered()` gaps

### 4.1 Two scans, three transitions

This is the *shipped* clock the poligon must be run against, not the slogan
in §1. Name grain is mixed (sentence for `claim`, section for `methods`,
document for absence). Act is not a score (A3–A4).

As shipped (`docs/host-integration.md`, `TaktReviewer.review`):

```text
Pack load → DecisionClient → scan 1 name → scan 2 judge → optional LLMClient act
```

| Transition | Scientific peer review | ReviewKit |
| --- | --- | --- |
| **Name** | This paragraph is Methods; this sentence is a claim; this span is a citation | `DecisionClient.decide`, one noul per `Function.id`. Tags only. |
| **Judge** | Methods too thin to replicate; claim unsupported; CONSORT item 8 absent from the report | Matching `Rule` + at most one `SourceUnit`. Fragment `defect`. Document `close` iff `covered()[F]` is empty. |
| **Act** | Reviewer comment; author revises in a later round | `LLMClient.complete_json` only for high-confidence `change`/`delete`/`insert`. Default for papers: skip (comment / `missing`). |

Name is not a takt. Judge is the only Pack path that calls
`takt.cascade_step`. Author revision is not the referee’s third tact
([`three-takt-vs-two-scan-optional-act.md`](three-takt-vs-two-scan-optional-act.md)
§7.4).

### 4.2 Missing Methods is `function_absent` at document

Worked example for poligon assumption A7 (sentence `function_absent` finds
missing Methods — false).

Scan 1 walks sentence → paragraph → section → document and asks, for each
node, whether it instantiates `methods` (and every other function). Suppose
the manuscript has Title, Abstract, Introduction, Results, Discussion, and
no procedure anywhere — the classic hollow / “egg” IMRaD shell (§6).

```text
state.covered()  →  {title: […], abstract: […], research_question: […],
                     results: […], discussion: […]}
gaps = ontology.function_ids() − set(covered())
     ∋ methods, evidence, …     # host sitko
```

Scan 2 on fragments never asks “is methods missing?” A Results sentence
that does not instantiate `methods` is the normal state of a Results
sentence. Scan 2 on the **document** runs the CloseRule:

```text
kind=close, function_id=methods, scope=document, when=function_absent
→ DecisionClient “present?” → VerdictKind.MISSING
```

That is the same object as `close-purposes` in
`tests/fixtures/notice.pack.json` and `close-conflict` in
`examples/packs/story.json`. The engine does not know it is a paper.

False friends:

1. **Methods-like sentence in the Introduction.** A tag on that sentence
   fills `covered()["methods"]` and *suppresses* close. Existential
   completeness is satisfied; located completeness (“there is a Methods
   *section*”) is not. Hosts that need the section filter `covered()` by
   node id / heading. They must not move `close` to sentence scope.
2. **Methods in a supplement.** PRISMA and many journals count it. Document
   `covered()` is right; a heading-strict journal overlays a located check.
3. **Thin Methods.** Presence is true; quality is a DefectRule on the tagged
   section (`function_present`, citing a unit that says what “enough to
   replicate / assess” means — Shannon’s communication requirement, CONSORT
   expanded bullets, ARRIVE Essential 10, whatever the overlay loaded).

### 4.3 Defect vs close for papers

| Observation | Rule | Verdict family |
| --- | --- | --- |
| No Methods anywhere | `close` / `function_absent` @ document | `missing` |
| Methods section exists, cannot be replicated | `defect` / `function_present` @ fragment (section) | `change` or `keep`+comment |
| Claim sentence with no linked evidence function in the tree | host set-check on `covered()`; optional document `close` on `evidence` if the *paper* never instantiates evidence | `missing` on `evidence`, not on the claim sentence |
| Claim sentence that overclaims the evidence that *is* tagged | `defect` on `claim` citing Popper / hedge unit | `change` → hedge, never a new statistic |
| Citation span whose bibliography entry is absent or fabricated | `defect` on `citation` citing a citation-integrity unit; host Crossref sensor | `change`/`delete` or human |
| Required TOP item (data availability) never named | `close` on `data_availability` | `missing` |

Collapsing thin Methods into “missing Methods” is the fused
`missing_elements` bug 0.24 removed. You cannot insert a section that is
already there; you judge it.

### 4.4 Act stays comments unless the profile says otherwise

A paper under review is closer to an evidentiary record than to a draft
contract. Inserting a methods paragraph the author never wrote is worse
than flagging absence (ISO/ICMJE lesson in the meta note). The scientific
profile’s `action_policy` should map reporting-boilerplate `defect`s to
comment or human_decision, and must not auto-apply numeric or citation
writes. Qwen, if bound at all, drafts a *comment body* or a hedge the
editor can show the author — it does not become the author.

---

## 5. Primers as `SourceUnit`s (URLs and titles in Pack data only)

Information theory and the scientific method are **criteria**, not Python.
They belong in `Pack.units`, cited by at most one rule each (`cited_unit`).
Core must not import Shannon, Popper, or COS. Product docs and
`examples/` must not grow a methods engine. The host versions the unit
the way it versions CONSORT 2010 vs 2025.

This research note records **title + URL** so a Pack author can fill
`SourceUnit.url` / `locator` / a short `text` gloss. It does not paste the
works. A Pack whose `text` is the whole *Bell System Technical Journal*
article, or the whole *Logic of Scientific Discovery*, is the domain-dump
failure mode.

### 5.1 Shannon — enough signal to reconstruct the experiment

| Field | Pack data (not engine code) |
| --- | --- |
| Title | Claude E. Shannon, “A Mathematical Theory of Communication,” *Bell System Technical Journal* 27 (1948) 379–423, 623–656 |
| URL | https://doi.org/10.1002/j.1538-7305.1948.tb01338.x |
| Suggested `id` | `unit-shannon-1948` |
| `force` | `guidance` (almost never journal-binding) |
| Rule it serves | `defect` on `methods` (and maybe `data_availability`): the named methods node does not carry enough information for a competent peer to reconstruct or audit the procedure |

Shannon is not a second cascade engine. The qualitative-information story
Takt already uses (Mazur 1970, communicate → communicate) is engineering
vocabulary for organs. The paper Pack uses Shannon as a **methods
completeness gloss**: noise, channel, what must be transmitted. A methods
section that says “we analysed the data” and stops is a low-information
communicate. That is `defect`, not `close`.

### 5.2 Popper — claims must be at risk

| Field | Pack data |
| --- | --- |
| Title | Karl Popper, *The Logic of Scientific Discovery* (English 1959; *Logik der Forschung* 1934), esp. the demarcation / falsifiability chapters |
| URL (entry) | https://plato.stanford.edu/entries/popper/ |
| Suggested `id` | `unit-popper-falsifiability` |
| `force` | `guidance` |
| Rule it serves | `defect` on `claim` when the statement is unfalsifiable, tautological, or insulated from the paper’s own evidence; optionally `close` on `evidence` if the document never instantiates evidence at all |

Falsifiability is a property of a **claim**, not of a Methods heading.
Name tags `claim` spans; Judge cites this unit. Act must not “fix” the
claim by inventing a test that was not run (fused-pass number-repair).

### 5.3 TOP — inspectability as completeness

| Field | Pack data |
| --- | --- |
| Title | Nosek et al., “Promoting an open research culture,” *Science* 348 (2015) 1422–1425 (TOP guidelines) |
| URL | https://www.cos.io/initiatives/top-guidelines · https://doi.org/10.1126/science.aab2374 |
| Suggested `id` | `unit-top-guidelines` |
| `force` | `binding` or `guidance` depending on the journal’s TOP level (0–3) |
| Rule it serves | `close` on `data_availability` / `code_availability` / `preregistration` when the journal’s level requires them and `covered()` is empty; `defect` when the named statement is “data available on request” at a level that forbids that hedge |

TOP is the open-science analogue of GDPR Art. 13: a closed information set
whose absence is a document property. CONSORT 2025’s Open science cluster
is a reporting-guideline projection of the same set. Version the unit when
COS or the journal changes levels; do not edit `instructions.md`.

### 5.4 Illustrative unit records

Shape only (`SourceUnit` fields from `pack.py`). Not a shippable Pack.

```json
{
  "unit-shannon-1948": {
    "id": "unit-shannon-1948",
    "source_id": "shannon-bstj-1948",
    "locator": "BSTJ 27 (1948)",
    "url": "https://doi.org/10.1002/j.1538-7305.1948.tb01338.x",
    "text": "Methods must transmit enough information to reconstruct the procedure.",
    "force": "guidance"
  },
  "unit-popper-falsifiability": {
    "id": "unit-popper-falsifiability",
    "source_id": "popper-lsd",
    "locator": "SEP: Karl Popper",
    "url": "https://plato.stanford.edu/entries/popper/",
    "text": "A scientific claim is at risk of being shown false by evidence.",
    "force": "guidance"
  },
  "unit-top-guidelines": {
    "id": "unit-top-guidelines",
    "source_id": "cos-top-2015",
    "locator": "Science 348:1422",
    "url": "https://www.cos.io/initiatives/top-guidelines",
    "text": "Journal TOP level determines required data, code, and preregistration statements.",
    "force": "binding"
  }
}
```

`text` is a gloss for the DecisionClient. `url` + `locator` are the audit
citation. The engine never fetches the URL.

---

## 6. Fighting low-quality, spam, and “egg” papers

**Egg paper**, in this note: a manuscript that instantiates the *genre
form* (IMRaD headings, an abstract, a reference list) without instantiating
the *functions* (methods a peer could assess, claims tied to evidence,
citations that refer to real works). Paper mills, tortured-phrase
paraphrase factories, and LLM shells are production methods. The Pack
diagnosis is hollow `covered()` plus integrity `defect`s — not a new
organ in ReviewKit.

Technical checks journals already run (iThenticate, Crossref, Retraction
Watch, image forensics) are **sensors**. They do not belong in
`src/reviewkit`. The host may feed their outputs into `DecisionClient`
state or as pre-tags. The Pack says which functions those sensors are
evidence for.

### 6.1 Fake and impossible references

LLM-written bibliographies routinely invent articles, mix real authors with
fake titles, and cite works that do not support the sentence (Alkaissi &
McFarlane-style case reports; later bibliometric audits). That is a
**citation** function with a DefectRule, not a prose instruction.

| Mechanism | Pack object | Host sensor (outside the engine) |
| --- | --- | --- |
| Reference list present as headings only, no bibliographic function tagged | `close` on `citation` if the venue requires citations | — |
| In-text citation whose bibliography row is missing | `defect` on that `citation` span | locator match, bibliography parse |
| Bibliographic row that Crossref / PubMed cannot resolve | `defect` citing a citation-integrity unit (`force=binding`) | Crossref / DOI API |
| Real paper, wrong claim (SciFact REFUTES / NEI) | `defect` on `claim` or `citation`, unit = “citation must support the claim” | retrieval + NLI, optional |
| Cited work is retracted | `defect` on `citation` | Retraction Watch / PubMed flags |

Act must not `INSERT` a real-looking reference to “support” the claim
([`decide-vs-fused-pass.md`](decide-vs-fused-pass.md) §5.2). The ethical Act
is `delete` / comment / human. Fabricating a source is a worse defect than
an unsupported sentence.

### 6.2 Unsupported claims

Name `claim` and `evidence` as different functions. Judge them separately.

- Document never instantiates `evidence` while it instantiates `claim` →
  `close` on `evidence` (existential: this paper does not show its work).
- A particular claim span overreaches tagged evidence → `defect` on `claim`
  citing Popper and/or a hedge unit (“in this sample”, not a new *n*).
- Table/figure not in the fragment → DecisionClient should return
  not-enough-info / human, not invent the cell.

This is the `#314` `paper` fixture generalised: n=12, conclusion claims
population effectiveness. The finding is overclaim. The Pack version is
`claim` present, `evidence` present-but-defective, no write of a p-value.

Joint defects (claim C is only bad relative to evidence E) are set-valued
Judge. 0.24 rules are 1 function × 1 optional unit. Hosts can run a second
Pack whose functions are pairs, or compute the join from `covered()` after
scan 1. Do not encode the join as fragment `function_absent` on the claim
sentence.

### 6.3 Recycled text and tortured phrases

Similarity (iThenticate, duplicate submission) and “tortured phrases”
(Cabanac, Labbé, Magazinov — paraphrased technical terms as paper-mill
fingerprints) are sensors on *any* function. They are not IMRaD items.

Pack-shaped options that do not grow an engine:

1. Host pre-tag: nodes above a similarity threshold are not eligible for
   `keep` on `methods` / `discussion` until a person looks.
2. DefectRule on every named IMRaD function citing a unit “must be original
   to these authors” (`force=binding` at the journal). The DecisionClient
   sees the sensor score in state.
3. Do not add an `originality` function unless you want it in `covered()`.
   Empty originality tags would then skip close if a mill paper’s heading
   “Introduction” is tagged as original because the model liked the prose.

Form-only IMRaD (all four headings, no tagged `methods`/`evidence` jobs) is
already caught by document CloseRules on the base ontology. That is the
egg-paper sitko: **headings are not functions**. Naming must tag the job,
not the outline.

### 6.4 Citation integrity beyond fakes

Citation manipulation (COPE): coercive citation, citation cartels, stuffing
the discussion with the mill’s own DOIs. A Pack cannot prove a cartel from
one manuscript. What it can do:

- `defect` on `discussion` / `citation` when citations do not engage the
  claim (unit: “citations support or contrast the claim,” SciFact-shaped).
- Host-level: unusual self-citation rate as DecisionClient context, not as
  a ReviewKit metric.
- `close` is the wrong tool: the citations *are* present.

### 6.5 What still needs a person

Image duplication, statistical fraud that `statcheck` cannot see, scope
fit, and “this RCT should not have been run” are not Pack theatre. Sensors
+ editor remain. The Pack’s job is to make **hollow form**, **missing
methods**, **fake references**, and **unsupported claims** cheap, typed,
and auditable (`function_id` + unit `locator`) so the editor does not spend
reviewer time on eggs.

---

## 7. Contrast with Temida legal Packs

Same engine, different Pack. That is the whole `#314` claim.

Temida’s source is not in this checkout. Wiring below is from ReviewKit
sockets, `docs/host-integration.md` naming Temida as a Pack host, and
[`three-takt-vs-two-scan-optional-act.md`](three-takt-vs-two-scan-optional-act.md)
§6 (Basal on `decide`, Qwen on `complete_json`). Argus/Temida orchestration
stays out of this library (`AGENTS.md`).

| Slot | Legal Pack (Temida notice / contract) | Scientific paper Pack |
| --- | --- | --- |
| Engine | ReviewKit 0.24 Pack path | Same |
| Sockets | `DecisionClient.decide` (name+judge), `LLMClient` (gated write) | Same |
| Ontology | Information items / clause types (`controller_identity`, `purposes`, playbook keys) | Genre jobs (`methods`, `claim`, `citation`, …) + optional CONSORT/PRISMA/ARRIVE overlay |
| Units | Statute locators, UODO/EDPB glosses, playbook positions | Checklist items + E&E; Shannon / Popper / TOP primers |
| `force` | `binding` for Art. 13 points; `guidance` for layered-notice commentary | `binding` for journal-required TOP/CONSORT; `guidance` for primers |
| CloseRule | Missing purposes on the notice | Missing methods (or data availability) on the paper |
| DefectRule | Named purposes omit legal basis | Named methods omit reconstructible procedure; named claim unfalsifiable; named citation unresolved |
| Act | Redline from approved language, else person | Comments; no invented results, numbers, or references |
| Profile | Language, escalate legal sense | Language, do not rewrite evidence |
| Gap API | `function_ids() − covered()` | Same call |
| What must not leak | Art. 13 list into `instructions.md` | CONSORT PDF into `instructions.md` |
| Composition | Notice Pack ≠ employment Pack ≠ DPA Pack | Paper Pack ≠ CONSORT overlay ≠ SPIRIT protocol Pack |

Portable: the triple ontology + units + rules, two scans, document-only
close, at most one cited unit per judge call. Not portable: function ids,
unit text, what “good enough” means, which Pack the host loads.

A host that copies `controller_identity` into a paper Pack, or CONSORT item
ids into a notice Pack, has ported the *instance*. A host that loads
`examples/packs/story.json` for a story, a notice Pack for Art. 13, and
`scientific_paper.json` for IMRaD is using the engine as designed.

Dike remains the rendering consumer. ReviewKit does not grow a CONSORT
engine or a GDPR engine.

---

## 8. Coordination with `examples/packs/scientific_paper.json`

Live paths and present/absent status: **§1.5**. This research PR does **not**
add the Pack JSON or a manuscript fixture and does **not** duplicate engine
code.

Coordination rules if/when
[`examples/packs/scientific_paper.json`](../../examples/packs/scientific_paper.json)
exists:

1. **This note’s function ids are sketches.** The JSON is the instance.
   Hosts and tests should key off the file, not copy §3.2 blindly.
2. **Prefer a topic-agnostic genre Pack** (IMRaD + claim/evidence/citation
   + optional openness functions), not a 30-item CONSORT dump in
   `examples/`. CONSORT/PRISMA/ARRIVE are overlays the host composes.
   `tests/test_docs_pack_canon.py` already keeps Polish-law tokens out of
   `examples/`; a full EQUATOR dump would be the scholarly version of the
   same mistake.
3. **Primers are units with `url` + short `text`.** Do not paste Shannon or
   Popper into the JSON `text` field beyond a gloss. Do not import those
   URLs from `src/reviewkit`.
4. **Integrity is rules + host sensors**, not new `Rule.kind`s. Fake
   references stay `defect` on `citation`. Missing methods stay `close` on
   `methods`.
5. **Profile stays behaviour.** A `paper.reviewer` folder may say “do not
   rewrite results.” It must not list CONSORT items or Popper quotes.
6. **Fixtures stay thin.** [`tests/fixtures/notice.pack.json`](../../tests/fixtures/notice.pack.json)
   is a two-function double. A paper Pack fixture, if tests need one, should
   be equally thin — not a copy of the product JSON. The in-tree manuscript
   today is the `"paper"` case in
   [`tests/test_conformance_corpus.py`](../../tests/test_conformance_corpus.py)
   (overclaim, n=12). A longer IMRaD fixture, when the platform PR lands one,
   is the poligon input for A1/A7/A9.

Until the example Pack lands,
[`examples/packs/story.json`](../../examples/packs/story.json) plus this note
is enough to implement against: the close-on-uncovered-function contract is
already tested (`test_host_sketch_names_then_judges_and_exposes_covered_gaps`
expects `conflict` / `resolution` gaps). A paper Pack is that test with
different ids. The poligon is not fully lit until both the JSON and a
section-scale manuscript exist; do not treat the two-sentence corpus string
as evidence that sentence-by-sentence name is cheap or sufficient.

---

## 9. What this Pack is not

1. **Not a novelty scorer.** Importance stays fused qualitative (A6, A10).
2. **Not a CONSORT interpreter inside ReviewKit.** Overlay Packs are data.
3. **Not three neural scans per sentence.** That is the slogan the poligon
   is meant to kill (A1, A2). Name may be a cheap classifier; Judge batches
   at section/document; Act is a queue of comments.
4. **Not a coverage score.** `|covered| / |ontology|` is not accept/reject
   (A3, A5).
5. **Not author ghostwriting.** ICMJE/COPE: reviewers do not become authors
   (A4).
6. **Not a plagiarism product.** Sensors feed the host; ReviewKit names and
   judges document functions.
7. **Not Temida.** Same sockets, different JSON, composition at the host /
   Fala boundary. Temida legal Packs are a second instance, not this poligon.
8. **Not an engine change.** If three-pass looks bad on a paper, tighten the
   reading (two scans + optional write + host score). Do not add a third
   `cascade_step`.

---

## 10. Verdict

**Use the scientific peer-review Pack as the poligon for three-pass, not as
a reason to grow a third cascade organ.**

The slogan `name sentence-by-sentence → judge → act/score` smuggles ten
false assumptions (A1–A10): sentence as universal grain, three neural
walks, coverage as a journal score, referee-as-author, frozen Name, headings
as functions, merit as a Pack id. A paper is the first document family
large, hierarchical, and ethically constrained enough to make those
assumptions fail in public. A notice or a three-function story cannot.

What survives is the *role* split already shipped: name tags, judge cites
one unit, act is optional and usually off, gaps are
`ontology − covered()`, missing Methods is document `close`, egg papers
fail as empty lists plus integrity `defect`s. Reporting guidelines and TOP
are already ontologies. IMRaD is already topic-agnostic: structure is
stable; content is data.

Ship the instance (genre Pack + manuscript fixture, §1.5) without changing
`src/reviewkit`. Run the measurements in §1.5. Keep Shannon, Popper, and
TOP in unit data. Keep Temida legal Packs on the same plant without sharing
function ids. Keep merit off the Pack. If the poligon shows F1/F2/F12 in
anger, the fix is host naming quality, overlay size, and optional act —
not a sentence-level CloseRule and not a score head on `TaktReviewer`.

---

## Sources

### ReviewKit (0.24)

- `src/reviewkit/pack.py` — unified `Rule` (`label` / `defect` / `close`);
  `SourceUnit`; `judge_rules`; `naming_functions`
- `src/reviewkit/state.py` — `ReviewState.covered()`
- `docs/host-integration.md` — two scans, host gaps, never fragment close
- [`docs/research/three-takt-vs-two-scan-optional-act.md`](three-takt-vs-two-scan-optional-act.md)
  — scans ≠ tacts; act is not a score
- [`docs/research/name-judge-act-cross-domain-meta.md`](name-judge-act-cross-domain-meta.md)
  — F1–F14; reporting vs merit
- [`examples/packs/story.json`](../../examples/packs/story.json) — genre Pack shape
- [`examples/packs/scientific_paper.json`](../../examples/packs/scientific_paper.json)
  — product instance **when present** (not in tree on this research branch)
- [`tests/fixtures/notice.pack.json`](../../tests/fixtures/notice.pack.json) — legal thin double (`close` on `purposes`)
- [`tests/test_conformance_corpus.py`](../../tests/test_conformance_corpus.py) — in-tree `"paper"` manuscript (overclaim)
- Issue #314 — one engine, umowa / rozprawka / artykuł / paper
- Issue #343 — fragment must not claim document-wide absence

### Peer review process

- ICMJE, responsibilities in the submission and peer-review process,
  https://www.icmje.org/recommendations/browse/roles-and-responsibilities/responsibilities-in-the-submission-and-peer-peview-process.html
- COPE, ethical guidelines for peer reviewers,
  https://publicationethics.org/guidance/guideline/ethical-guidelines-peer-reviewers
- COPE & STM, paper mills research report (2022),
  https://publicationethics.org/resources/research/paper-mills-research

### Reporting / openness (overlays and units)

- Hopewell et al., CONSORT 2025, *BMJ* 2025;388:e081123,
  https://www.consort-spirit.org/
- Page et al., PRISMA 2020, *BMJ* 2021;372:n71,
  https://www.prisma-statement.org/
- Percie du Sert et al., ARRIVE 2.0, *PLOS Biology* 2020,
  https://arriveguidelines.org/
- STROBE statement, https://www.strobe-statement.org/
- Nosek et al., TOP guidelines, *Science* 2015;348:1422–1425,
  https://www.cos.io/initiatives/top-guidelines
- Chauvin et al., COBPeer vs usual peer review, *BMC Medicine* 2019,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC6864983/
- SciScore (MDAR / ARRIVE / RRID), https://www.sciscore.com/
- Penelope.ai journal checks, https://penelope.ai/

### Structure / argument

- CASRAI, “IMRaD Structure”
- Sollaci LB, Pereira MG. The introduction, methods, results, and discussion
  (IMRAD) structure: a fifty-year survey. *CMAJ* 2004;171(1):47–48.
- Shannon CE. A mathematical theory of communication. *Bell Syst Tech J*
  1948. https://doi.org/10.1002/j.1538-7305.1948.tb01338.x
- Popper K. *The Logic of Scientific Discovery*. Stanford Encyclopedia
  entry: https://plato.stanford.edu/entries/popper/

### Integrity sensors (host, not engine)

- Cabanac G, Labbé C, Magazinov A. tortured phrases / paper-mill fingerprints
- Nuijten M, `statcheck`, https://github.com/MicheleNuijten/statcheck
- SciFact (SUPPORTS / REFUTES / NEI) as claim–evidence decide vocabulary
- Crossref REST API; Retraction Watch database

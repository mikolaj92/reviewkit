# Scientific peer review as Pack

Research note. No engine, API, or profile change. The product Pack JSON, if
any, belongs in `examples/packs/scientific_paper.json` (or a host repo) — not
in `src/reviewkit`.

**Question.** Can journal-style peer review of a scientific paper be a
ReviewKit Pack: a topic-agnostic ontology of paper *jobs*, reporting
checklists as rule overlays, integrity checks as `defect` / `close` plus
`SourceUnit`s, and primers (Shannon, Popper, TOP) as Pack *data*?

**Verdict.** Yes, for the part of peer review that is already a completeness
and integrity game. No, for merit, novelty, and importance. The engine does
not change. Temida (or any host) loads a different Pack than a legal notice;
the sockets stay `DecisionClient.decide` and optional `LLMClient.complete_json`.

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

Sibling notes cover the meta, not this instance:
[`name-judge-act-cross-domain-meta.md`](name-judge-act-cross-domain-meta.md)
(roles vs fused merit),
[`covered-and-close-scope.md`](covered-and-close-scope.md)
(document-only close; CONSORT/PRISMA/IMRaD operators),
[`pack-as-game-cross-domain.md`](pack-as-game-cross-domain.md)
(game vs profile; scholarly checklist encodings),
[`three-takt-vs-two-scan-optional-act.md`](three-takt-vs-two-scan-optional-act.md)
(Temida Basal/Qwen wiring; editor vs author rewrite),
[`decide-vs-fused-pass.md`](decide-vs-fused-pass.md)
(scientific QA failure modes of fused rewrite).

---

## 1. How peer review actually works

Peer review is not one LLM pass over a PDF. It is a staged control process
with several roles, several decision vocabularies, and several checklists
that already look like Packs. ICMJE and COPE are explicit that **reviewers
advise and editors decide**; authors revise. ReviewKit must not collapse
those three agents into one `complete_json`.

### 1.1 Roles

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

### 1.2 Decisions

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

### 1.3 Checklists as ontology / rules patterns

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

## 2. Why a topic-agnostic ontology works

The usual objection: “physics is not psychology; you cannot have one paper
Pack.” That objection confuses **content** (data on the document) with
**structure** (jobs the document must perform). Peer review already treats
them differently. Reviewers in every empirical field ask the same four
questions IMRaD encodes: what is the question, how did you look, what did
you find, what does it mean (CASRAI IMRaD Structure; Sollaci & Pereira,
*CMAJ* 2004, on IMRaD’s 20th-century takeover of original articles).

### 2.1 Stable jobs, variable payload

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

### 2.2 What the base paper ontology is (research sketch)

Illustrative ids only. Product ids live in
`examples/packs/scientific_paper.json` when that file lands; this note must
not fork a second JSON. The shape is the story Pack’s shape
(`opening` / `conflict` / `resolution` in `examples/packs/story.json`):
genre jobs, not topic keywords.

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

### 2.3 Overlays stay overlays

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

### 2.4 What topic-agnostic does *not* buy

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

## 3. Mapping onto name → judge → act and `covered()` gaps

### 3.1 Two scans, three transitions

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

### 3.2 Missing Methods is `function_absent` at document

Worked example, the one this note exists to lock.

Scan 1 walks sentence → paragraph → section → document and asks, for each
node, whether it instantiates `methods` (and every other function). Suppose
the manuscript has Title, Abstract, Introduction, Results, Discussion, and
no procedure anywhere — the classic hollow / “egg” IMRaD shell (§5).

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

### 3.3 Defect vs close for papers

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

### 3.4 Act stays comments unless the profile says otherwise

A paper under review is closer to an evidentiary record than to a draft
contract. Inserting a methods paragraph the author never wrote is worse
than flagging absence (ISO/ICMJE lesson in the meta note). The scientific
profile’s `action_policy` should map reporting-boilerplate `defect`s to
comment or human_decision, and must not auto-apply numeric or citation
writes. Qwen, if bound at all, drafts a *comment body* or a hedge the
editor can show the author — it does not become the author.

---

## 4. Primers as `SourceUnit`s (URLs and titles in Pack data only)

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

### 4.1 Shannon — enough signal to reconstruct the experiment

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

### 4.2 Popper — claims must be at risk

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

### 4.3 TOP — inspectability as completeness

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

### 4.4 Illustrative unit records

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

## 5. Fighting low-quality, spam, and “egg” papers

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

### 5.1 Fake and impossible references

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

### 5.2 Unsupported claims

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

### 5.3 Recycled text and tortured phrases

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

### 5.4 Citation integrity beyond fakes

Citation manipulation (COPE): coercive citation, citation cartels, stuffing
the discussion with the mill’s own DOIs. A Pack cannot prove a cartel from
one manuscript. What it can do:

- `defect` on `discussion` / `citation` when citations do not engage the
  claim (unit: “citations support or contrast the claim,” SciFact-shaped).
- Host-level: unusual self-citation rate as DecisionClient context, not as
  a ReviewKit metric.
- `close` is the wrong tool: the citations *are* present.

### 5.5 What still needs a person

Image duplication, statistical fraud that `statcheck` cannot see, scope
fit, and “this RCT should not have been run” are not Pack theatre. Sensors
+ editor remain. The Pack’s job is to make **hollow form**, **missing
methods**, **fake references**, and **unsupported claims** cheap, typed,
and auditable (`function_id` + unit `locator`) so the editor does not spend
reviewer time on eggs.

---

## 6. Contrast with Temida legal Packs

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

## 7. Coordination with `examples/packs/scientific_paper.json`

At the time this note was written, `examples/packs/` contained only
`story.json`. A sibling product change may land `scientific_paper.json`.
This research PR does **not** add that file and does **not** duplicate
engine code.

Coordination rules if/when the JSON exists:

1. **This note’s function ids are sketches.** The JSON is the instance.
   Hosts and tests should key off the file, not copy §2.2 blindly.
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
6. **Fixtures stay thin.** `tests/fixtures/notice.pack.json` is a two-function
   double. A paper fixture, if tests need one, should be equally thin — not
   a copy of the product JSON.

If the platform PR has not landed yet, `story.json` plus this note is
enough to implement against: the close-on-uncovered-function contract is
already tested (`test_host_sketch_names_then_judges_and_exposes_covered_gaps`
expects `conflict` / `resolution` gaps). A paper Pack is that test with
different ids.

---

## 8. What this Pack is not

1. **Not a novelty scorer.** Importance stays fused qualitative.
2. **Not a CONSORT interpreter inside ReviewKit.** Overlay Packs are data.
3. **Not three neural scans per sentence.** Name may be a cheap classifier;
   Judge batches at section/document; Act is a queue of comments.
4. **Not author ghostwriting.** ICMJE/COPE: reviewers do not become authors.
5. **Not a plagiarism product.** Sensors feed the host; ReviewKit names and
   judges document functions.
6. **Not Temida.** Same sockets, different JSON, composition at the host /
   Fala boundary.

---

## 9. Verdict

Peer review is already name → judge → (someone else’s) act. Reporting
guidelines and TOP are already ontologies with presence/quality splits.
IMRaD is already a topic-agnostic function list: the structure of a paper
is stable; the content is data. ReviewKit 0.24 already implements the
game.

Ship scientific peer review as a **Pack instance** (genre jobs + integrity
rules + primer units), optionally composed with CONSORT/PRISMA/ARRIVE
overlays, judged with document `close` when `covered()` is empty (missing
Methods is the canonical gap) and fragment `defect` when a named job is
hollow, fake, or unfalsifiable. Keep merit off the Pack. Keep Shannon,
Popper, and TOP out of engine code: titles and URLs live in unit data.
Keep Temida legal Packs on the same plant without sharing function ids.

Egg papers fail as empty `covered()` on methods/evidence/citation plus
`defect`s on fabricated references — the same sitko as a notice that never
names purposes. That is the point of one engine.

---

## Sources

### ReviewKit (0.24)

- `src/reviewkit/pack.py` — unified `Rule` (`label` / `defect` / `close`);
  `SourceUnit`; `judge_rules`; `naming_functions`
- `src/reviewkit/state.py` — `ReviewState.covered()`
- `docs/host-integration.md` — two scans, host gaps, never fragment close
- `examples/packs/story.json` — genre Pack shape
- `tests/fixtures/notice.pack.json` — legal thin double (`close` on `purposes`)
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

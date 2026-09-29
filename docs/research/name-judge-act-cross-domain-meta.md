# Research: is name / judge / act a sound meta for cross-domain document checks?

**Status:** research only. No code, API, or pipeline changes.  
**Question:** is a two-scan plus optional act pipeline a sound *meta* for document checking across legal contracts / privacy notices *and* scientific papers, grant proposals, clinical protocols, and standards compliance?  
**Verdict (preview):** **refine.** Keep the three *roles*. Do not hard-wire three LLM passes on every node. Treat Pack(ontology + rules + units) as the domain payload, not as a prompt dump.

---

## 0. The proposed meta

Call the candidate architecture **3-takt** (three beats, not three Takt engines):

| Beat | Role | What it does | Typical output |
| --- | --- | --- | --- |
| **1. Name** | Tag / extract | Walk sentence → paragraph → section → document. Name functions, clause types, reporting items, information types, or rhetorical moves. | Spans + labels + locators. No verdict, no rewrite. |
| **2. Judge** | Evaluate | Compare named units against an ontology, rule set, and source units (required clauses, checklist items, playbook positions, GDPR information types, ISO audit criteria). | Findings: present / absent / defective / conflict, with evidence and confidence. |
| **3. Act** | Optional rewrite | LLM rewrite *only* for change / delete / insert above a confidence floor. Comment, flag, question, and risk stay non-writing. | Bounded `replace` / `insert` / `delete` with `original_text` and locator. |

Two scans are mandatory (name, then judge). Act is gated: skipped for comment-only review, skipped below confidence, skipped when policy says `human_decision`.

This is *not* the same cut as ReviewKit's existing cascade. ReviewKit already walks sentence → paragraph → section → document *per tact* and already separates `ReviewFinding` from `ReviewAction`. The question here is whether **naming**, **judging**, and **acting** should be *separate control beats* — possibly separate model calls — rather than one fused JSON response per node.

---

## 1. What ReviewKit already is (so the meta is not invented in a vacuum)

ReviewKit is a domain-agnostic review *engine*, not a legal checker and not a one-shot rewriter (`README.md`). The public contract is already split:

- **Findings** observe. **Actions** propose a response. The library validates and applies actions deterministically.
- Topology is always `sentence → paragraph → section → document` (`REVIEW_ENGINE_SCOPES` in `pipeline.py`). Products do not add domain-specific pipeline stages.
- One fused LLM detector per node produces a structured `ReviewResponse` with both findings and actions (`detectors.py`, `prompts.py`).
- Takt v0.3.2 fuses those raw signals and the homeostat decides `actuation` / `interlock` / `stable`.
- `ActionPolicy` then fail-closes writing actions on confidence, severity, protected patterns, unique match, and apply hints (`policy.py`). The employment-contract example already maps `typo` → apply and `risky_clause` / `missing_clause` / `legal_rewrite` → `human_decision`.
- Domain knowledge enters only through **profiles** (TOML + Markdown) and **`ReviewContextProvider`**. Issue #314's stated boundary: ReviewKit = *how* to review; profile/context = *what* and *against which truth*.

So ReviewKit already has a **logical** name/judge/act:

```text
LLM (fused name+judge+propose) → Finding (observation)
                               → Takt homeostat + ActionPolicy (gate)
                               → Effector + deterministic DOCX edit (act)
```

The proposed meta would **unfuse the LLM**: name first, judge second, rewrite third and optional. Hierarchy stays. Deterministic apply stays. The change is *when* the model is allowed to decide a rewrite, and *what* it is allowed to see while naming versus judging.

That distinction matters. Most of the literature below splits **roles**. Very little of it requires **three model calls on every sentence**.

---

## 2. Analogues in the wild

If 3-takt were a good meta, mature review systems would keep the same three roles even when they fuse the UI. They do.

### 2.1 Contract review: extract, then playbook, then redline

**Kira / Litera** is the cleanest industrial name-then-judge. Proprietary Smart Fields extract *verbatim* spans for 1,400+ clause types trained on lawyer hours; they do not draft. Generative Smart Fields may then answer a question, but Litera grounds them on the extracted fields rather than letting a standalone LLM invent clauses ([Litera, “What Is Multi-Layer AI?”](https://www.litera.com/blog/what-multi-layer-ai-how-kira-improves-genai-accuracy-contract-review); [Generative smart fields FAQ](https://support.litera.com/article/Generative-smart-fields-FAQ-613398)). The Analysis Grid is a judge surface: humans (and later GenAI) evaluate named provisions against deal questions. Redlines are a later act.

**Ironclad** splits the same three roles in product language, not just in ML:

- **Clause Library** = ontology of standard language (governance, not review).
- **AI Playbooks** = named clause type + trigger rules + preferred / fallback / non-standard *positions* (judge).
- **Precise Redlining / AI Assist** = optional rewrite from a pre-approved position, tracked, with exception routing to a clause approver ([Ironclad Playbooks overview](https://support.ironcladapp.com/hc/en-us/articles/12275685560215-Ironclad-AI-Playbooks-Overview); [Precise Redlining](https://support.ironcladapp.com/hc/en-us/articles/28661084734999-Use-AI-Precise-Redlining-to-Review-a-Contract); [Clause Library vs Playbooks](https://support.ironcladapp.com/hc/en-us/articles/30659446762647-Clause-Library-Overview)).

Ironclad is explicit that library and playbook are *not currently connected*. That is a real-world failure of packing ontology and rules into one Pack — and a warning, not a reason to stuff both into a prompt.

**CUAD** (Hendrycks, Burns, Chen, Ball; NeurIPS Datasets 2021, [arXiv:2103.06268](https://arxiv.org/abs/2103.06268)) defines contract review as *highlight the span a human should look at* for 41 clause types. There is no rewrite head. The research task *is* Name. Judgment and redline remain human. That is the high-stakes default.

### 2.2 Privacy notices: conceptual model, then completeness rules

**CompAI** (Amaral, Abualhaija, Briand, 2024; Linklaters collaboration) does not ask an LLM to “review this privacy policy.” It (1) parses the policy into a GDPR *conceptual model* of information types, (2) applies mandatory vs optional completeness *rules* conditioned on a short questionnaire (controller vs processor, DPO, transfers, …), (3) emits a report with article-level explanations. Reported accuracy ≈ 96% vs keyword baseline on >200 policies. Rewrite is out of scope. This is Pack(ontology + rules) plus Name, then Judge. Act is a lawyer.

**AudAgent** (2025) goes further: formalize the policy (Name), annotate runtime data practices (Name at a different layer), then automata + ontology graphs (Judge). Act is an alert, not a policy rewrite.

GDPR Articles 12–14 are themselves a completeness ontology. Element-wise PRESENT / ABSENT / INSUFFICIENT is a judge vocabulary. Drafting a missing Art. 13(1)(e) recipients clause is a different competence.

### 2.3 Scientific peer review: admin name, checklist judge, editorial act

Journal workflow is already staged ([COPE ethical guidelines for peer reviewers](https://publicationethics.org/guidance/guideline/ethical-guidelines-peer-reviewers); [ICMJE recommendations](https://www.icmje.org/recommendations/browse/roles-and-responsibilities/responsibilities-in-the-submission-and-peer-peview-process.html)):

1. **Administrative / technical check** — files, metadata, word limits, required statements. This is Name of completeness units, mostly deterministic.
2. **Desk review** — scope, novelty, basic methods. Fused human judge. Often *no* rewrite invitation.
3. **Integrity checks** — similarity, ethics, COI. Separate sensors.
4. **External peer review** — critique of argument, methods, claims vs evidence. Judge. Reviewer comments are *not* the paper rewrite.
5. **Editorial decision + revision** — Act is the *author's*, under editor constraints. Reviewers who rewrite the paper for the author are doing the wrong job.

**COBPeer** (Chauvin et al., *BMC Medicine* 2019, [PMC6864983](https://pmc.ncbi.nlm.nih.gov/articles/PMC6864983/)) is the empirical punch: early-career reviewers with a CONSORT-based tool detected incomplete reporting far better than usual peer review (sensitivity 86% vs 20% on key CONSORT items). Specificity dropped (61% vs 77%). A structured Judge pass *raises recall of checklist defects* and *over-calls*. That trade-off is the meta, not a bug to paper over.

**CONSORT 2025** (30-item checklist + expanded bullet elicitation; [consort-spirit.org](https://www.consort-spirit.org/)) and **PRISMA 2020** (Page et al., *BMJ* 2021; 27 items + expanded checklist + flow diagram) and **SPIRIT 2025** (34 protocol items) are Packs: ontology of reporting units + rules of completeness. They do not generate manuscript text. **RAPID** (LLM + RAG over CONSORT / CONSORT-AI) automates the *judge report* (reported ~92% / ~84% item accuracy) and still does not auto-rewrite the paper. That is two-scan, act = human or a later gated rewrite.

Scientific *merit* review (novelty, importance, identifiability of the contribution) is a different judge, and it does *not* decompose cleanly into named units. NIH's Simplified Peer Review Framework (Importance; Rigor and Feasibility; Expertise and Resources; [NIH SRF](https://grants.nih.gov/policy-and-compliance/policy-topics/peer-review/simplifying-review/framework)) is a fused qualitative score plus a separate administrative completeness gate (SF424 conformity, page limits, NOFO responsiveness — applications that fail this are *not reviewed*). Two judges, different evidence, different acts (triage vs score vs award). Forcing both through one Name inventory would be a category error.

### 2.4 Clinical protocols and standards: evidence, finding, action

**ISO 19011** defines the split in vocabulary, not in software:

- *audit criteria* — the Pack (requirements used as reference);
- *audit evidence* — verifiable records / statements / observations (Name);
- *audit findings* — evaluation of evidence against criteria (Judge);
- *audit conclusions* — the aggregated outcome;
- *correction* vs *corrective action* — Act, and they are not the same thing ([ISO 19011](https://www.iso.org/standard/70017.html); ISO 9001:2015 10.2).

ISO 9001 Auditing Practices Group guidance insists auditors confirm documented evidence for **correction, cause analysis, and corrective action** *separately* before closing a nonconformity. Fusing “here is the missing sentence, I already rewrote it” is exactly the response auditors reject.

**ISO/IEC 17025** 8.8: internal audit produces information on conformity; management then implements correction and corrective action without undue delay. The laboratory document is evidence, not the CAPA form.

Clinical trial *protocols* sit on SPIRIT; *reports* sit on CONSORT; *GCP* (ICH E6) adds process evidence (TMF, monitoring, SAE reporting) that is not in the protocol text. A protocol checker that only names sections will miss process units that live in other documents. Pack must include *which units are in this artifact* vs *which units are in the trial master file*. That is a Pack problem, not a prompt-stuffing problem.

### 2.5 Annotation pipelines: Prodigy and Doccano

**Prodigy**'s documented advice is to annotate NER and textcat in *two passes*, then merge (`data-to-spacy`). Combined `blocks` UIs are allowed but discouraged: “it makes it harder for annotators to focus” and “more difficult to iterate on one label scheme” ([Prodigy custom interfaces](https://prodigy.ai/docs/custom-interfaces)). That is Name vs Judge as separate human tasks, for the same reason 3-takt wants separate model tasks: different error, different ontology, different iteration cadence.

**Doccano** splits project types (text classification, sequence labeling, seq2seq) and treats auto-labeling as a *pre-Name* that humans then Judge. Seq2seq (the Act analogue) is a different project, not a side effect of span tagging.

spaCy's production pipeline is also staged (`tok2vec → ner → …`) with the same known cost: early errors cannot be recovered unless you add a later review recipe.

### 2.6 Hierarchical NLP

**HAN** (Yang et al., NAACL 2016) builds document representations word → sentence → document with attention at each level. **HiCoBERT** (2026) does segment-then-document encoding for legal judgments because transformers cannot take the whole judgment. **Legal concept alignment** work encodes sentence / paragraph / document jointly against a law-centric knowledge graph.

These support ReviewKit's *plant*, not 3-takt per se. They say: local naming without a document layer misses globally defined functions (a limitation already filed as reviewkit #343 — fragment-scoped absence claims). Hierarchy is necessary for Name. It does not decide whether Judge should share the Name call.

### 2.7 Classify-then-critique, then (maybe) revise

**Constitutional AI** (Bai et al., 2022) is critique-then-revision as *separate generations*. The paper keeps the critique step even when larger models close the quality gap, because the critique is the audit trail.

**Self-Refine** (Madaan et al., NeurIPS 2023) is generate → feedback → iterate with three prompt types (`Init`, `Feedback`, `Iterate`). Gains are real (~20% absolute on their suite) and *cost a second and third call*. Unguided self-refine can drift; later Refine-n-Judge work adds an external Judge that must *prefer* the revision before it is accepted — which is ReviewKit's policy/homeostat, not another LLM writer.

**LLM-as-a-judge** (Zheng et al., 2023, and the 2024 survey “From Generation to Judgment”) is a specialized Judge role. The literature's recurring failure modes — position bias, verbosity bias, self-preference — are exactly why Judge should not be the same sample as Act.

### 2.8 Tool-calling vs structured decide

This is the Act-stage fork, not a Name/Judge fork.

| Primitive | What it guarantees | Fit |
| --- | --- | --- |
| **Structured outputs** (JSON schema, constrained decoding) | Shape of a decision record. Model must fill the schema. No side effects. | Name and Judge: extract spans, emit findings. ReviewKit's `complete_json` + Pydantic schemas live here. |
| **Tool / function calling** | Routing: *whether* to call, *which* tool, with arguments. Side effects happen in the host. Schema constrains args, not the decision to act. | Act *selection* when several effectors exist (replace vs insert vs open a Fala child). Dangerous if the model can skip Judge by calling `rewrite` directly. |

For a review engine that must fail closed, **structured decide** is the default: the model proposes a typed action; the host (Takt + `ActionPolicy` + unique-match + protected patterns) decides apply vs interlock. Tool-calling is appropriate at the *Fala host* boundary (which effector to run), not inside the document plant's rewrite head. Giving the writer a `apply_redline` tool is how you accidentally fuse Judge into Act.

---

## 3. Argument FOR: 3-takt is a sound meta

### 3.1 The roles are already how high-stakes review works

Every domain above that *matters* (ISO audit, GDPR completeness, CONSORT, Ironclad playbooks, Kira fields, NIH administrative vs merit review) refuses to let “I rewrote it” stand in for “here is the evidence, here is the criterion, here is the finding.” ReviewKit's own README principle 4 is the same sentence: findings describe observations; actions describe what might be done.

If the meta did not split roles, `corrected.docx` would silently encode a legal or clinical conclusion the engine claims not to make.

### 3.2 Name is a different statistical object than Judge

- Name is span tagging / information extraction (CUAD, Kira Smart Fields, HAN local attention, Doccano sequence labeling). Errors are misses and over-tags. Evaluation is span F1.
- Judge is comparison to a *closed* inventory of units (checklist item, playbook position, GDPR information type, ISO clause). Errors are false presence, false absence, wrong severity. Evaluation is item-level completeness + calibration.
- Act is conditional generation under a locator. Errors are meaning change, ungrounded insertion, stale `original_text`.

Fusing them in one JSON blob optimizes none of the three losses. It also makes it impossible to swap a cheap NER / smart-field model into Name while keeping a stronger model for Judge — the Kira multi-layer pattern.

### 3.3 Absence claims require a second scan against complete units

ReviewKit issue #343 is the existence proof inside this repo: a fragment that does not see a distant clause must not claim document-wide absence. Name can proceed locally. Judge of *missing_element* is a document- (or Pack-) scoped operation over the named inventory plus a completeness flag on the source (`source_document.complete` in `prompts.py`). That is two scans by construction. Fusing them at sentence scope is how you get hallucinated “missing indemnification” on page 2 of a 40-page MSA.

CONSORT item 14b (why the trial ended or was stopped) and PRISMA item 16a (study selection) are the same shape: you cannot judge absence from the abstract.

### 3.4 Act as an optional, confidence-gated rewrite matches real policy

Ironclad does not auto-insert fallback language without a playbook position and (often) a clause approver. ISO does not treat a correction as a closed CAPA. ReviewKit's default `min_confidence_for_auto_apply`, `require_llm_apply_hint`, and category map (`typo` apply / `legal_rewrite` human) are already this beat. Making Act a *separate* optional call, only for writing actions that already passed Judge, prevents the model from “helpfully” rewriting while it is still naming.

Constitutional AI and Self-Refine both pay extra tokens *on purpose* so the revision is conditioned on a critique, not on a vibe.

### 3.5 Packs are how you go cross-domain without forking the engine

Issue #314 asked for executable proof that umowa / rozprawka / artykuł / paper share one engine. Fala's `DOMAIN_PACKS.md` already states the composition rule: core stays domain-agnostic; a pack is a vocabulary layer mapping product concepts onto Impulse / Association / Reaction / Homeostat; packs do not implement product engines. ReviewKit profiles are the document-shaped version of that: Markdown instructions + TOML policy + optional context provider.

A Pack(ontology + rules + units) is what lets CONSORT-2025, an Ironclad playbook, and a GDPR conceptual model ride the same plant. Prompt-stuffed “you are a CONSORT reviewer…” does not version, cannot be tested item-by-item, and drowns in the middle of a long context ([Liu et al., “Lost in the Middle,” TACL 2024](https://aclanthology.org/2024.tacl-1.9/)).

### 3.6 Human annotation science agrees

Prodigy: do not ask one annotator to NER and classify at once. COBPeer: a checklist tool changes sensitivity. ISO: evidence ≠ finding ≠ action. When humans cannot fuse the roles reliably, a single LLM sample is not a better fusion — it is a hidden fusion.

---

## 4. Argument AGAINST: 3-takt is not a sound *universal* meta

### 4.1 Cascading error is the oldest NLP pipeline bug

Pipeline NER → relation extraction is known to cap recall at the first stage (Zelenko / Zhou / Chan & Roth lineage; clinical joint models, Wei et al. *JAMIA* open; filter-separator joint IE, 2024). If Name misses the clause, Judge never sees it, Act never fires. Joint models exist *because* the presence of a relation can recover a missed entity.

Document review has the same loop:

- A playbook violation (Judge) can tell you the span you named as `limitation_of_liability` is actually `indemnity` wrapping a cap.
- A proposed rewrite (Act) can reveal that the “missing” unit was present under a synonym the Name ontology lacked.
- Scientific merit: “this claim is unsupported” is not a named reporting item; it is a Judge over argument structure. Forcing a CONSORT-like inventory first will under-call novelty and over-call format.

A hard Name→Judge freeze with no reconciliation wave (ReviewKit already has a bounded whole-to-local reconciliation after document scope, issue #312) repeats the pipeline mistake that joint IE spent a decade undoing.

### 4.2 Many review tasks have no ontology worth naming

The `story.teacher` profile is aesthetic and pedagogical. There is no closed unit list. HAN-style hierarchy still helps. A GDPR conceptual model does not. Forcing Pack-shaped Name on a narrative review produces fake precision: tags like `climax` / `pacing` that Judge cannot falsify against source units.

Grant *merit* (NIH Factor 1 Importance) and journal novelty are similar. Checklists help reporting completeness; they do not score importance. CONSORT-AI concordance can be high while the trial is still a bad idea. A 3-takt meta that pretends every domain is completeness-against-units will ship a false sense of coverage.

### 4.3 Fused structured output is often enough — and cheaper

For local, high-precision, low-ontology work (typo, grammar, obviously broken reference, a missing Oxford comma in a style guide), Name and Judge are the same proposition: “this span is wrong for this local rule.” A second scan doubles latency and cost for no new evidence. Self-Refine's extra calls pay off on hard generation; they are waste on span-local copy-edits that ReviewKit already auto-applies at high confidence.

Kira does not run a second LLM to “judge” a governing-law Smart Field. The field *is* the judgment that this span is the governing-law clause. Human review in the grid is the Judge, and it is not an LLM pass.

### 4.4 Split models disagree on vocabulary

The most boring production failure: Name emits `termination_for_convenience`; the playbook key is `exit_rights`. Judge sees no unit, reports missing, Act inserts a second clause. Ironclad's Clause Library vs Playbooks disconnect is this bug in a shipping CLM.

Without a *shared* Pack that binds labels, rules, and units to the same IDs, 3-takt *increases* inconsistency compared with one fused prompt that at least uses one vocabulary in one sample.

### 4.5 LLM-as-judge is biased in ways Name/Act then amplify

Zheng et al. and the 2024 survey: position bias, length bias, self-preference. If Judge is an LLM over a long named inventory, middle items drop (“Lost in the Middle” again). Act then rewrites the *salient* defects and leaves the middle-of-the-Pack holes. A fused pass with a short, retrieved rule set can beat a full-inventory second scan.

COBPeer's specificity drop is the human version: structured Judge over-calls. Automatic Judge without a human grid will over-redline.

### 4.6 Cross-domain “one meta” is a product claim, not a scientific one

ReviewKit can honestly say *one plant, one effector contract, many profiles*. That is #314. Claiming that *every* profile must run two LLM scans plus optional rewrite is a different claim. Scientific peer review, ISO audit, and contract playbook share a *logical* triple (evidence, finding, action) and do *not* share a *process* triple (two full-document neural scans). Auditors sample; they do not NLP every sentence. Study sections do not re-score NIH Factor 3 as a span tagger.

A meta that ignores sampling, materiality, and dual-control (two human reviewers, editor vs referee, clause approver vs requester) will look complete in a diagram and fail the actual control environment.

### 4.7 Act-as-LLM-rewrite is the wrong default in several domains

- **ISO / 17025:** the document under audit is evidence. Rewriting it inside the audit tool tampers with the record. Act is an NCR, not a `replace_text`.
- **Peer review:** reviewers must not ghostwrite. ICMJE even restricts AI-assisted review. Act is comments to the editor/author.
- **Privacy notices:** a completeness miss often requires a *policy decision* (what is our retention period?), not a fluent sentence.
- **Clinical protocols:** an inserted SPIRIT item that was never true is a worse defect than a missing item.

3-takt's beat 3 (“LLM rewrite only for change/delete/insert above confidence”) is correct *when the artifact is a draft under edit*. It is incorrect when the artifact is an *evidentiary record* or a *submission being judged*. The meta must make Act polymorphic (comment / NCR / redline / no-op), not assume rewrite.

---

## 5. Deliverable (1): where 3-pass is necessary vs where 2 fused is enough

“3-pass” here means **separate Name, Judge, and (optional) Act computations** — not necessarily three LLM calls, and not necessarily all four hierarchy levels.

### 5.1 Three-pass is necessary

Use an explicit Name inventory, a second Judge over Pack units, and a gated Act when **all** of the following hold:

1. **Closed unit list** with independent identity (CONSORT/PRISMA/SPIRIT items, GDPR Art. 13/14 information types, playbook clause types, ISO clauses, required-contract-clause lists).
2. **Absence is a first-class finding.** Local fused review cannot see other sections (reviewkit #343).
3. **Writing would change legal, clinical, or compliance meaning.** Rewrite must be conditioned on a stored finding, not emitted as a side effect of tagging.
4. **Different skills or models.** Extractive span models (Kira / CUAD-style) outperform general LLMs on Name; a reasoner or a rule engine outperforms them on Judge.
5. **Audit trail requires evidence ≠ finding ≠ action** (ISO 19011; ReviewKit lineage events).

Canonical cases:

| Domain | Name | Judge | Act |
| --- | --- | --- | --- |
| M&A / contract playbook | Smart-field / CUAD spans | Playbook position vs preferred/fallback | Redline from approved language, else exception |
| Privacy notice | Information types in conceptual model | Mandatory/optional completeness rules | Usually comment; rewrite only for template notices |
| RCT report / systematic review | Section/item spans (methods, outcomes, flow) | CONSORT / PRISMA item status | Author revision; auto-rewrite only for boilerplate reporting sentences |
| Trial protocol | SPIRIT section map | 34-item completeness + internal consistency (outcomes vs SAP) | Comments / controlled inserts of *template* language, never invented methods |
| ISO / 17025 document set | Documented information vs process evidence | Criteria → findings | NCR / CAPA; do not silently edit the evidence |
| Grant admin completeness | SF424 / NOFO required elements | Pass/fail before merit | Return for correction, not scientific rewrite |

In these cases a **fused** Name+Judge at sentence scope is not “faster 3-takt.” It is a different, weaker method that systematically fails absence and cross-section consistency.

### 5.2 Two fused beats are enough

Fuse Name+Judge (and often propose-comment) in **one** structured call when:

1. **No closed ontology** — style, pedagogy, narrative, exploratory scientific critique of novelty.
2. **Defect is local and positive** — the span is present and malformed (typo, grammar, dangling reference, inconsistent defined term *in this paragraph*).
3. **Act is comment-only** — reviewer role, not drafter role.
4. **Unit list is tiny and already in the profile** — a five-bullet house style. Retrieval and a second scan add noise.
5. **Cost/latency dominates** and the profile's auto-apply set is copy-edit (`typo` / `grammar` / `formatting`).

Canonical cases: `story.teacher`; line-edit of an already CONSORT-complete manuscript; “is this paragraph unclear?”; NIH Factor 1 prose critique (after admin completeness already passed).

### 5.3 Hybrid (the actual meta worth keeping)

Almost every production system is hybrid, not pure 3 or pure 2:

```text
deterministic / extractive Name  ─┐
                                  ├─ Judge (rules + LLM-as-judge on hard items)
fused local LLM copy-edit        ─┘
                                  └─ Act only if writing + confidence + policy
```

- Run **fused** detectors on sentence/paragraph for local defects (today's ReviewKit).
- Run **Pack Judge** at section/document (and on reconciliation targets) for units, absence, and playbook positions.
- Run **Act LLM** only for writing actions that Judge already approved and policy did not interlock — optionally a *new* sample conditioned on the finding, in the Constitutional AI / Self-Refine sense.

That is two *mandatory* computational scans at whole-document granularity (Name inventory + Judge), plus fused local tacts, plus optional rewrite. It is not “3 LLM calls × N sentences.”

NIH already does this: administrative completeness (scan 1, mostly deterministic) then scientific critique (scan 2, fused qualitative). Ironclad: detect clause (Name) then position match (Judge) then optional precise redline (Act). CompAI: parse types then fire rules; no rewrite.

---

## 6. Deliverable (2): failure modes of splitting name / judge / act

| # | Failure | What it looks like | Who already hit it | Mitigation (meta-level, not an implementation spec) |
| --- | --- | --- | --- | --- |
| F1 | **Cascade miss** | Name drops a span; Judge reports absence; Act inserts a duplicate | Joint IE literature; #343 inverse (false absence) | Bounded reconciliation; allow Judge to request re-Name of a locator; never treat Name as frozen |
| F2 | **Cascade hallucination** | Name over-tags; Judge trusts the tag; Act rewrites the wrong function | COBPeer specificity drop; LLM-as-judge verbosity | Judge must re-read source text, not only the tag; confidence independent of Name |
| F3 | **Vocabulary split** | `exit_rights` ≠ `termination_for_convenience` | Ironclad Library vs Playbooks | One Pack, one ID space; Judge input is Pack IDs not free strings |
| F4 | **Scope laundering** | Sentence Name of a local gap promoted to document absence | reviewkit #343 | Judge of absence only if `source_complete`; fragments cannot emit missing-element on the whole |
| F5 | **Stale locator** | Act rewrites using Name offsets after an earlier apply | ReviewKit conflict / unique-match policy | Act against current plant; one writer; no tool-loop mid-scan |
| F6 | **Premature Act** | Writer called because confidence was on Name, not Judge | Tool-calling skip-to-rewrite | Structured decide; Act sample gated on finding_id + Judge confidence; no `rewrite` tool in Name |
| F7 | **Lost interaction** | Indemnity and liability cap only jointly defective | Joint NER+RE; legal cross-default | Judge may look at *sets* of named units, not 1:1 |
| F8 | **Pack too large** | 200 checklist items stuffed into Judge prompt; middle items die | Lost-in-the-Middle; RAPID uses RAG for a reason | Retrieve units by Name hits *and* by required-but-unhit IDs (explicit absence candidates) |
| F9 | **Wrong Act polymorphism** | Completeness miss auto-rewritten into a protocol as if it were true | ISO evidence tampering; ICMJE reviewer-as-author | Act types: comment / NCR / template-insert / source-edit. Default comment in evidentiary domains |
| F10 | **Double counting** | Fused local detector and Pack Judge both flag the same typo | Hierarchical HAN overlap | Dedup by locator+dimension; lineage keeps both; canonical finding as today |
| F11 | **Self-preference on Act** | Same model judges its own rewrite as fine | LLM-as-judge self-bias; Refine-n-Judge | Policy/homeostat is *not* the writer; optional second model or deterministic guards |
| F12 | **Cost blow-up** | 3 calls × 4 levels × N nodes | Self-Refine token cost | Name can be extractive/non-LLM; Judge batched at section; Act only on writing queue |
| F13 | **Human-loop mismatch** | Grid reviewers correct Name tags that Judge never sees | Kira Analysis Grid vs unattended GenAI | If humans edit Name, re-run Judge; do not cache findings across tag edits |
| F14 | **Ontology drift** | CONSORT 2010 Pack run on a 2025 manuscript | CONSORT 2025 restructure (open science section) | Version the Pack; pin it in the profile digest (lineage already wants profile digest, #313) |

The split does not create F4/F5/F10 — fused ReviewKit already has them — but it **multiplies F1, F3, F6, F8, F12**. Any 3-takt adoption that does not budget for reconciliation (#312) and shared Pack IDs is a net loss.

---

## 7. Deliverable (3): when Pack(ontology + rules + units) beats prompt-stuffed instructions

### 7.1 What a Pack is (in this repo's language)

Not a Fala vocabulary pack (`takt.mojo` mapping cascade names onto Impulse), and not a fat ReviewKit module. A **review Pack** is the domain payload that today is smeared across `instructions.md`, `required-clauses.md`, `risky-clauses.md`, TOML dimensions, and ad-hoc `ReviewContextProvider` blobs:

- **Ontology** — typed functions / information types / checklist items / clause IDs.
- **Rules** — how to judge a unit given evidence (mandatory vs optional, preferred vs fallback, severity).
- **Units** — source-of-truth snippets: statute text, playbook positions, CONSORT expanded bullets, ISO clause language, template inserts.

Fala's rule still applies: the engine does not become the pack; the host/profile/context boundary carries it (`AGENTS.md`, `DOMAIN_PACKS.md`, issue #314).

### 7.2 Pack wins

| Condition | Why prompt stuffing loses |
| --- | --- |
| **Closed, versioned inventory** (CONSORT 2025, PRISMA 2020, SPIRIT 2025, GDPR conceptual model, 1,400 Kira fields, Ironclad positions) | Instructions.md cannot stay in lockstep; no item-level tests; no digest in lineage |
| **Absence testing** | A prompt cannot *prove* a unit was considered; a Pack ID with hit/miss can |
| **Long documents** | Liu et al. 2024: middle context drops. Retrieve the 8 relevant units plus the 3 required-unhit IDs, do not paste 40 pages of playbook |
| **Dual control / expert edit** | Lawyers edit playbook positions; methodologists edit CONSORT expansions. They will not edit a 2k-token system prompt. CompAI's questionnaire + conceptual model is the pattern |
| **Cross-product reuse** | Same GDPR ontology on a notice, a DPIA, and a processor DPA. Same SPIRIT pack on protocol and on TMF completeness. Prompt copies diverge |
| **Deterministic rules exist** | “If no DPO and not public authority, skip DPO contact completeness.” That is a rule, not a vibe. CompAI's 23-point lift over keywords is this |
| **Audit** | ISO wants criteria cited. A Pack ID + rule ID + evidence locator *is* the audit finding. A chat instruction is not |
| **Mixed model routing** | Extractive Name model + LLM Judge + template Act. Prompt stuffing assumes one model sees everything |

### 7.3 Prompt-stuffed instructions still win

| Condition | Why a Pack is overhead |
| --- | --- |
| **Open-ended critique** (novelty, voice, pedagogy, Factor 1 importance) | No honest unit list. Packs become theatre |
| **Tiny local style** | Five bullets in `instructions.md` is the Pack |
| **One-off review** | Cost of ontology engineering exceeds the document |
| **Synonym-heavy prose with no canonical IDs** | A frozen ontology under-calls; a prompt can analogize (with hallucination risk you accept) |
| **Human is the Judge** | Kira grid, journal editor. The model should Name and get out. Extra structure does not help the human |

### 7.4 Anti-pattern: fake Packs

A Markdown file that restates CONSORT in prose, dumped wholesale into every paragraph prompt, is **prompt stuffing with better branding**. A Pack that is not retrieved, not IDed, not versioned, and not used for absence accounting is not a Pack.

Conversely, putting legal or CONSORT **engines** inside ReviewKit would violate the host/Fala composition rule. The Pack is data + rules for `ReviewContextProvider` / profile markdown; the plant and effectors stay generic.

---

## 8. Domain matrix (cross-check of the question)

| Domain | Closed ontology? | Absence-critical? | Rewrite ethical? | Recommended shape |
| --- | --- | --- | --- | --- |
| Legal contracts, playbook review | Yes (clause types + positions) | Yes | Yes, from approved language | **3-role**, extractive Name, Pack Judge, gated Act |
| Legal contracts, diligence extraction | Yes (CUAD / Kira fields) | Partial (report “not found”) | No | **Name + grid Judge**; no Act |
| Privacy notices | Yes (GDPR types) | Yes | Rare (policy choice) | **3-role**, Act = comment / template |
| Scientific papers, reporting | Yes (CONSORT/PRISMA) | Yes | Author's job | Name + Pack Judge; Act = comments |
| Scientific papers, merit | No | No | No | **Fused** qualitative Judge; no Pack theatre |
| Grant proposals, admin | Yes (NOFO / SF424) | Yes | Return to applicant | Deterministic Name + Judge; almost no LLM |
| Grant proposals, merit | Weak (NIH factors) | No | No | Fused, like journal review |
| Clinical protocols | Yes (SPIRIT) + process units outside the file | Yes | Dangerous if invented | Pack Judge; Act = comments / controlled templates |
| ISO / 17025 / standards | Yes (clauses) | Yes, plus sampling | **Must not** edit evidence | Name evidence, Judge findings, Act = NCR |
| Editorial / teaching | No | No | Yes | **Fused** local tacts; today's ReviewKit |

The question asked “across domains — legal … AND scientific …”. The honest answer: **the roles transfer; the pass schedule and the Act type do not.**

---

## 9. Deliverable (4): verdict

**Refine. Do not keep 3-takt as “always two full LLM scans plus rewrite.” Do not reject the role split.**

Keep as meta:

1. **Three roles** — Name (typed spans/functions), Judge (Pack-relative findings), Act (polymorphic, default conservative).
2. **Hierarchy** — sentence → paragraph → section → document as the plant, with bounded downward reconciliation. This is already ReviewKit/Takt. It is orthogonal to 3-takt and should not be collapsed.
3. **Findings ≠ actions**, deterministic apply, fail-closed policy. Already shipped.
4. **Pack(ontology + rules + units)** as the domain payload at the profile/context/Fala-host boundary, versioned and retrieved, not stuffed.
5. **Structured decide** for Name and Judge; host-side homeostat for whether Act runs. Tool-calling belongs at Fala effector routing, not as `rewrite()` from the namer.

Refine:

1. **Do not mandate three LLM calls per node.** Name may be extractive or fused-local. Judge of Pack units is a *second scan at the scopes that can see the units* (section/document + reconciliation), not a second sentence loop. Act is a *queue*, not a tact.
2. **Act is polymorphic.** Rewrite / template-insert / comment / NCR / no-op. Confidence gating applies only to source-text mutation. Evidentiary artifacts default to comment/NCR.
3. **Name is not frozen.** Judge (and humans in a grid) may trigger bounded re-Name. That is #312 generalized, not a new product orchestrator.
4. **One ID space.** If Pack labels and detector dimensions diverge, split is worse than fusion (F3).
5. **Merit vs completeness are different judges.** CONSORT/PRISMA/admin completeness can be 3-role. Novelty, importance, pedagogy stay fused. Profiles choose; the engine does not grow a `if legal` branch (#314).

Reject:

1. ReviewKit-as-CONSORT-engine or ReviewKit-as-Ironclad. Domain engines stay engines; composition at host/Fala (`AGENTS.md`).
2. Tool-calling Act that can fire without a finding_id.
3. Prompt-stuffed “you are a GDPR/CONSORT/ISO auditor” as a substitute for a Pack.
4. Whole-document rewrite as beat 3. The engine's contract is bounded locators (`prompts.py`: do not rewrite the whole document).

### One sentence

**3-takt is a sound control meta (evidence, criterion, gated mutation) for any domain that has a Pack; it is a bad execution meta if it means three neural passes on every sentence, and it is the wrong Act if the document is evidence rather than a draft.**

---

## 10. Implications if this were ever implemented (not in this PR)

Research recommendations only, for whoever next touches engine vs host:

- Keep fused LLM detectors for local copy-edit and open-ended profiles.
- Add Pack-shaped context as *retrieved units + required-unhit IDs* at section/document Judge, via `ReviewContextProvider`, not via core branches.
- Gate writing-action *generation* (not just apply) on Judge confidence for Pack-backed profiles; comments stay free.
- Preserve lineage from Name span → Judge finding → Act → render receipt (#313).
- Measure the split with the COBPeer trade-off: recall of absence/completeness vs specificity / over-redline, on the four-domain corpus idea in #314 — not with a single “LLM quality” score.

This document does not specify APIs, schemas, or a Fala journal graph.

---

## References (selected)

**ReviewKit / siblings**

- ReviewKit `README.md`, `pipeline.py` (`REVIEW_ENGINE_SCOPES`), `prompts.py`, `policy.py`, `takt_reviewer.py`
- Issues #312 (bounded reconciliation), #313 (lineage), #314 (one engine, many profiles), #343 (absence vs fragment)
- Fala `docs/DOMAIN_PACKS.md`, `docs/CYBERNETIC_MAPPING.md`; Takt `docs/CONCEPTUAL_MODEL.md`

**Contract / privacy**

- Hendrycks, Burns, Chen, Ball. *CUAD: An Expert-Annotated NLP Dataset for Legal Contract Review*. NeurIPS Datasets 2021. https://arxiv.org/abs/2103.06268
- Litera. “What Is Multi-Layer AI? How Kira Improves GenAI Accuracy in Contract Review.” https://www.litera.com/blog/what-multi-layer-ai-how-kira-improves-genai-accuracy-contract-review
- Litera. Generative smart fields FAQ. https://support.litera.com/article/Generative-smart-fields-FAQ-613398
- Ironclad. AI Playbooks overview; Precise Redlining; Clause Library vs Playbooks. support.ironcladapp.com (articles `12275685560215`, `28661084734999`, `30659446762647`)
- Amaral, Abualhaija, Briand. *CompAI: A Tool for GDPR Completeness Checking of Privacy Policies using Artificial Intelligence*. 2024. https://compai.uni.lu/

**Scientific / clinical reporting**

- Page et al. *The PRISMA 2020 statement*. BMJ 2021;372:n71. https://www.bmj.com/content/372/bmj.n71
- CONSORT 2025 / SPIRIT 2025. https://www.consort-spirit.org/
- Chauvin et al. COBPeer vs usual peer review. *BMC Medicine* 2019. https://pmc.ncbi.nlm.nih.gov/articles/PMC6864983/
- Liu et al. CONSORT-AI concordance review. *Nat Commun* 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC10883966/
- NIH Simplified Peer Review Framework. https://grants.nih.gov/policy-and-compliance/policy-topics/peer-review/simplifying-review/framework
- ICMJE. Responsibilities in the submission and peer-review process. https://www.icmje.org/recommendations/browse/roles-and-responsibilities/responsibilities-in-the-submission-and-peer-peview-process.html
- COPE. Ethical guidelines for peer reviewers. https://publicationethics.org/guidance/guideline/ethical-guidelines-peer-reviewers

**Standards / audit**

- ISO 19011, guidelines for auditing management systems (criteria, evidence, findings, conclusions)
- ISO 9001:2015 10.2, nonconformity and corrective action; ISO 9001 APG guidance on reviewing nonconformity responses
- ISO/IEC 17025:2017 8.8 internal audits

**NLP / LLM method**

- Yang et al. Hierarchical Attention Networks for Document Classification. NAACL 2016. https://aclanthology.org/N16-1174/
- Liu et al. Lost in the Middle: How Language Models Use Long Contexts. TACL 2024. https://aclanthology.org/2024.tacl-1.9/
- Bai et al. Constitutional AI: Harmlessness from AI Feedback. 2022. https://arxiv.org/abs/2212.08073
- Madaan et al. Self-Refine: Iterative Refinement with Self-Feedback. NeurIPS 2023. https://arxiv.org/abs/2303.17651
- Zheng et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. 2023; plus “From Generation to Judgment” survey, 2024
- Prodigy custom interfaces (NER vs textcat two-pass). https://prodigy.ai/docs/custom-interfaces
- Doccano auto-labeling vs human review. https://doccano.github.io/doccano/

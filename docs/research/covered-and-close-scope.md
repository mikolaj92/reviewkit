# Covered tags and CloseRule scope

Research note. No product change. The question is whether ReviewKit 0.24 is right
to run `CloseRule` / `function_absent` **only at document scope**, and **only
after** scan-1 naming has filled `ReviewState.covered()`, never at sentence or
paragraph.

The locked host contract is explicit:

- Fragment judge: `defect` only. Never `close`. Never `when=function_absent`.
- Document judge: `close` / `function_absent` only when `covered()` has no nodes
  for that function.
- Host gaps: `ontology.function_ids() − set(state.covered())`.

This note treats that rule as a claim about **completeness**, and tests it against
fields that already operationalise completeness on hierarchical documents:
CONSORT (trial reports), PRISMA (systematic reviews), mandatory legal clauses,
academic IMRaD section requirements, and SOX / risk-and-control matrices.

**Verdict in one paragraph.** The current rule is the only sound reading of
*existential* completeness once naming is a local tag and closing is “is this
function present in the document at all?”. Sentence- or paragraph-level close of
that same predicate is a type error and a false-positive factory. The rule is
incomplete, not false, for two other completeness operators that reporting
guidelines, contracts, and control matrices actually use: *located* completeness
(the function must occur in a declared home) and *iterated* completeness (each
slot of a repeating type must house it). Those gaps are real, they are
mid-hierarchy, and they are not an argument for fragment `CloseRule`.

## 1. What the engine actually computes

Scan 1 names every enabled sentence, paragraph, section, and document against the
whole ontology. A tag is a local yes: this node instantiates function `F`.
`covered()` inverts the tag map: `F → [node_id, …]`. Scan 2 then:

- on a fragment, judges quality of functions **already tagged on that node**
  (`defect` / `function_present`);
- on the document, asks a noul “present?” only for functions with an empty
  `covered()` list (`close` / `function_absent`).

Pack validation encodes the same split: `label` and `defect` must be
`scope=fragment`; `close` must be `scope=document`. `judge_rules` drops
`function_absent` on any non-document node even if a pack somehow carried one.

Write the predicates without engine vocabulary:

- `Instantiates(n, F)` — naming tagged node `n` with function `F`.
- Existential coverage: `Covered(F) ⇔ ∃ n. Instantiates(n, F)`.
- Current close: fire `function_absent(F)` iff `¬Covered(F)`.

Naming is an open-world local observation. Close is a closed-world claim about
the **whole named population**. You cannot infer `¬∃ n. Instantiates(n, F)` from
`¬Instantiates(this_sentence, F)`. That is the entire case for document-only
close, and it does not depend on legal or medical subject matter.

Three completeness operators show up in the comparison fields. Only the first is
what `CloseRule` implements:

| Operator | Logical form | Typical home |
| --- | --- | --- |
| Existential | `∃ n. Instantiates(n, F)` | The document / instrument / report as a whole |
| Located | `Instantiates(home(F), F)` | Title, named section, numbered article |
| Iterated | `∀ s ∈ Slots. Instantiates(s, F)` | Each annex, each trial arm, each process, each party block |

`defect` is not a fourth completeness operator. It is a quality judgement on a
node that **already** instantiates `F`. A purposes clause that exists and is
vague is a defect. A purposes clause that does not exist anywhere is a close.
Collapsing those two is how fused-pass `missing_elements` used to lie.

`Function.attach_to` looks like a located-home hint (`sentence` / `paragraph` /
`section`). Naming still offers every function at every scope, and `covered()`
counts a tag on any node. The current close therefore treats a sentence tag as
sufficient existential evidence even when the function’s declared home is a
section. That is a live hole in *located* completeness, not a reason to close at
sentence.

## 2. CONSORT: a checklist on the whole report, with a few true loci

CONSORT 2025 is a 30-item minimum set for reporting a randomised trial, plus a
participant-flow diagram and an expanded checklist whose bullets unpack each
item (Hopewell et al., simultaneously in *BMJ*, *JAMA*, *Lancet*, *Nature
Medicine*, *PLOS Medicine*, 2025). EQUATOR classifies the guideline as applying
to the **whole report**, not to an individual section.

The checklist is nonetheless **section-grouped**: Title and abstract; Open
science; Introduction; Methods; Results; Discussion. Item 1a is “Identification
as a randomised trial” under Title. Item 1b is a structured abstract. Methods
items (trial design, outcomes, randomisation, blinding, statistical methods)
and Results items (participant flow, baseline, outcomes and estimation, harms)
are grouped where a reader expects to look, not where a sentence-level
closed-world test would be valid.

What completeness means here:

- **Existential (most items).** Journals and CONSORT endorsers score whether the
  item is reported in the manuscript, usually with a page number. EQUATOR’s
  “whole report” classification matches document-level `covered()`. If
  randomisation sequence generation appears anywhere the methods discussion can
  point to, item 8/9-class content is present. PRISMA makes the non-prescriptive
  location rule explicit; CONSORT’s practice is the same for the bulk of items
  even without that sentence in the statement.
- **Located (a minority).** Item 1a is not “the word randomised occurs
  somewhere.” Identification **as a randomised trial in the title** is the
  point: indexing, screening, and reader orientation fail if the identifier sits
  only in Methods. The abstract is a second, parallel completeness universe
  (CONSORT-abstracts), not a paragraph of the body.
- **Defect, not close.** The 2025 expanded checklist’s bullets are quality of a
  present item (measurement variable, analysis metric, aggregation, time point
  for each outcome). That is `function_present` + `defect` once Outcomes is
  tagged, not `function_absent` on every methods sentence that does not list
  those bullets.

Mid-hierarchy detection is real for CONSORT, and it is **section-shaped**, not
sentence-shaped. Completeness gaps that document-only close misses:

1. Title-locus items tagged on a methods sentence (`randomised` in the protocol
   summary, not in the title).
2. Abstract-locus items satisfied only in the body (or only in the abstract).
3. Flow-diagram items that are narrative in Results but absent as the required
   figure — a *form* of the function, not mere existence of related words.

Fragment-level close would mark every Results paragraph as missing trial
registration (Open science), and every Introduction sentence as missing the
participant-flow counts. That is not how any CONSORT completeness audit is
done. Page-level “reported on page _” is already coarser than a sentence and
finer than “somewhere in the PDF”; it is a retrieval coordinate for a
document-level item, not a local absence finding.

## 3. PRISMA: location is a template, presence is the rule

PRISMA 2020 is a 27-item checklist in seven sections (Title, Abstract,
Introduction, Methods, Results, Discussion, Other information), plus a separate
abstract checklist and a flow diagram (Page et al., *PLOS Medicine* / *BMJ*,
2021). The explanation and elaboration document states the completeness rule in
the direction ReviewKit already chose:

> Although PRISMA 2020 provides a template for where information might be
> located, the suggested location should not be seen as prescriptive; the
> guiding principle is to ensure the information is reported.

Essential elements may live in the main report **or** as supplementary material;
journal word limits are an explicit reason not to treat section membership as
the obligation. That is existential completeness with a suggested home, which is
exactly `covered()` plus optional host display of *where* the tag landed.

Exceptions that still matter:

- **Title item 1** (“Identify the report as a systematic review”) is
  locus-strict in the same way as CONSORT 1a. A methods sentence that says
  “this systematic review…” does not identify *the report* in the bibliographic
  sense.
- **Abstract** is again a parallel instrument. PRISMA-A is not “the first
  paragraph of the body.” Absence of an eligibility-criteria sentence in the
  abstract is an abstract-checklist gap even if Methods is complete.
- **Flow diagram** is a required *form*, like CONSORT’s.

PRISMA’s essential/additional split is also not fragment close. Essential
elements are framed as reporting the **presence** of a method or result; authors
may report absence of a method (“we did not contact individuals to identify
studies”) when that helps. Local silence is not evidence of a missing method.
Document-level close after naming is the only way to distinguish “never
instantiated” from “not this paragraph.”

If a host wants PRISMA section grouping, it should group **findings**, not
change the quantifier. A methods function tagged only under Discussion is a
located-completeness warning *after* `Covered(F)` is true, which is the opposite
of `function_absent`.

## 4. Mandatory legal clauses: set completeness of an instrument

Legal “mandatory clauses” are the intuition people reach for when they want
sentence-level close: this paragraph should have contained X. The instruments
that actually impose mandatory content usually quantify over the **instrument**,
not the paragraph.

**Information-set obligations (existential on the notice or contract).** GDPR
Article 13 requires the controller, when collecting personal data from the data
subject, to provide “all of the following information”: identity of the
controller, purposes and legal basis, recipients, transfers, retention,
rights, and so on. The article does not assign those items to numbered
paragraphs of a privacy notice. Completeness is whether the data subject was
given the set. The ReviewKit notice-pack fixture (`controller_identity`,
`purposes`, document `close` on `purposes`) is this operator. A sentence about
the controller that does not mention purposes is not a purposes gap; it is a
sentence that was never a purposes node.

**Contract-shall-stipulate lists (existential on the DPA or employment
instrument).** GDPR Article 28(3) requires processing to be governed by a
contract that “shall stipulate, in particular” documented instructions,
confidentiality, Article 32 measures, sub-processor conditions, assistance with
data-subject rights, deletion or return, and audit. The list is items the
**contract** must contain. Standard contractual clauses exist because the
obligation is on the instrument as a whole, not on each recital.

EU transparent-and-predictable working conditions (Directive 2019/1152) and
national implementations (German Nachweisgesetz; Spanish Royal Decree 723/2026
of 9 September 2026) require essential terms in writing: parties, start,
place, duties, pay, hours, leave, notice. Spain’s 2026 decree is unusually
clear about *where*: the obligation is satisfied if the information is already
in the written contract, and **if the contract contains only part of it, the
rest may be provided in additional written documents**. Completeness is of the
information set delivered to the employee, not of a single clause’s
neighbourhood. Polish practice for an employment contract is the same shape:
the instrument must determine parties, kind of work, place, remuneration,
working-time dimension, start date — without a statutory requirement that
remuneration live in article 4 and nowhere else.

**Where document-only close misses local absence:**

1. *Repeating slots.* A framework agreement with three schedules of services:
   remuneration tagged in Schedule A covers `Covered(remuneration)` for the
   whole pack even if Schedules B and C are silent. That is iterated
   completeness. The universe is each schedule, not each sentence and not the
   document.
2. *Separate instruments treated as one tree.* A non-compete or processor
   addendum has its own mandatory set (duration and consideration; Art. 28
   list). If the host concatenates them into one `ReviewDocument`, existential
   close on the bundle is the wrong universe. The fix is a pack boundary (one
   document node per instrument), not sentence close.
3. *Form-and-locus rarities.* Some acts require a specific form in a specific
   place (written termination; a title that must say “agreement for the
   processing of personal data”). Those are located completeness, analogous to
   CONSORT 1a.
4. *Wrong-home tags.* If naming tags `purposes` on a marketing slogan in the
   header, `covered()` suppresses close. That is a naming / defect problem, or
   a located-home filter on `attach_to`. It is not evidence that close should
   have run on the slogan’s sentence.

Fragment close false positives in this domain are the everyday bad legal
reviewer: flagging the remuneration clause as “missing notice period,” the
parties block as “missing GDPR rights,” each recital as “missing Art. 28(3)(h)
audit.” Those are not local absences. They are other functions, judged against
the wrong universe.

Defect remains the right tool once a function **is** tagged: a purposes
paragraph that names no legal basis is a present, defective purposes node.

## 5. Academic papers: IMRaD is section-complete, not sentence-complete

Empirical papers in the sciences and social sciences are expected to realise
Introduction, Methods, Results, and Discussion as **sections with
non-overlapping jobs** (the IMRaD convention; see e.g. CASRAI’s IMRaD Structure
entry). A paper is IMRaD-complete when:

1. Introduction states the question against background without previewing
   findings;
2. Methods describes procedure in enough detail to assess or replicate, and
   contains no findings;
3. Results reports what was found without interpretation;
4. Discussion interprets against the question and prior literature.

CASRAI is explicit that **content in the wrong section is a structural defect
even when all four headings are present** — interpretation in Results is the
usual case. Journals add further required sections or subsections
(Limitations, Data availability, Author contributions) with varying strictness.
Some venues print Methods after Discussion or in a supplement; the *content*
must still exist.

Mapping onto the three operators:

- **Existential.** “This paper reports a method.” Document `covered()` on a
  `methods` function is the right first filter. A supplement or a relocated
  Methods block still counts, as PRISMA allows for reviews.
- **Located.** “There is a Methods **section**.” A methods-like sentence in the
  Introduction does not discharge the section requirement for venues that
  enforce IMRaD headings. Document-only close **misses** that: any tag anywhere
  suppresses `function_absent`. This is the strongest everyday case against
  treating existential close as the only completeness check. It is still not
  sentence close: the universe is the section node (or the heading + body),
  which ReviewKit already has in the plant.
- **Defect.** Methods too thin to replicate, Results that interpret, Discussion
  that never states limitations — quality of a present section, i.e. fragment
  `defect` at section scope, not `function_absent` at sentence scope.

Sentence-level close of `limitations` would fire on every sentence except the
limitations paragraph. No journal reviewer works that way. Section-level
“this Discussion never instantiates limitations” is mid-hierarchy close whose
universe is the Discussion node, which is **not** the current `CloseRule`
(document only) and **not** a sentence rule.

## 6. SOX and control matrices: completeness is an assertion, precision is the scope

SOX 404 / PCAOB AS 2201 audits of internal control over financial reporting
treat **completeness** as a financial-statement assertion about a significant
account or disclosure: all transactions and disclosures that should be included
are included. Existence/occurrence is the dual. Neither assertion is evaluated
by asking whether a single invoice “contains” the completeness control.

The work is hierarchical and top-down (AS 2201.21): financial statements →
entity-level controls → significant accounts and relevant assertions →
processes. A risk-and-control matrix (RCM) records that nesting: account,
assertion, risk, control. Gaps are missing *links* in that matrix (no control
mapped to this assertion in this process), not missing sentences in a policy
PDF.

AS 2201.23 is the precision analogue of CloseRule scope:

- Some entity-level controls only **indirectly** affect the chance of a
  misstatement. They change how much lower-level testing you do; they do not
  discharge the assertion.
- Some monitor lower-level controls but are **not precise enough** by
  themselves.
- Some **are** precise enough that the auditor need not test additional
  controls for that risk.

Document-level close is the analogue of an entity-level control that *is*
precise enough for an existential question: “does this company have a revenue
recognition policy at all?” It is the wrong analogue for “does order-to-cash
have a cutoff control at a ‘would prevent or detect’ precision?” That second
question is iterated/located completeness at process scope. PCAOB does not
solve it by testing every transaction for the absence of the corporate code of
ethics (fragment close). It also does not solve it by stopping at “we saw a
policy somewhere” when the ELC is imprecise (naive document-only close).

Walkthroughs (AS 2201.37–.38) are the canonical mid-hierarchy absence detector:
follow a transaction through the process and notice the point at which a
necessary control is missing. The unit is a **process point**, not a sentence
and not the 10-K as a whole. Translating that into ReviewKit terms: if the
plant node *is* the process description (a section), section-scoped close on
that node’s children is coherent. If the plant node is a sentence inside a
narrative policy, it is not.

AS 2201.40–.41 add a useful negative: it is not necessary to test every control
that touches an assertion, nor to care how the control is labelled. Redundant
coverage is allowed. Existential `covered()` with many node ids for one
function is therefore not a problem for close; it is extra evidence of
presence. Close cares about empty lists.

## 7. Can completeness gaps be detected mid-hierarchy?

Yes, when the obligation’s quantifier is mid-hierarchy. The comparison fields
do this constantly. They do **not** do it at sentence scope except where the
sentence *is* the locus (a title; a form field; a table cell).

Valid mid-hierarchy universes, with field examples:

| Universe | Field example | What empty `covered()` inside it means |
| --- | --- | --- |
| Whole instrument | GDPR Art. 13 notice; Art. 28 DPA; CONSORT/PRISMA item present in the report | Current `CloseRule` |
| Named section / article | IMRaD Methods; CONSORT Methods cluster as a retrieval home; contract article that is the non-compete | Located close; current rule misses it |
| Parallel front matter | Title; structured abstract | Located close on a tiny document |
| Repeating slot | Each schedule, each trial arm, each SOX process, each party | Iterated close; current rule misses it if any slot is tagged |
| Process point | Walkthrough step in an RCM | Iterated/located at section-or-coarser, not sentence |

Invalid mid-hierarchy universe:

| Universe | Why it fails |
| --- | --- |
| Sentence or ordinary paragraph | Local `¬Instantiates` does not entail global `¬∃`. The node was never the candidate home of the function. |

The plant already has section nodes. The missing design is not “run `CloseRule`
on every layer.” It is “declare the close universe on the rule,” defaulting to
document because that is the only universe naming currently justifies without
further structure.

## 8. When document-only close misses local absence

These are the true negatives of the current rule — absences a human completeness
audit would catch and 0.24 close will not.

1. **Locus-strict identifiers.** CONSORT 1a / PRISMA title item 1 / journal
   “this is a randomised trial / systematic review” in the title. A body tag
   fills `covered()` and suppresses close.
2. **Required section that exists only as scattered sentences.** IMRaD Methods
   with no Methods heading; Discussion with no limitations subsection where the
   venue requires one. Sentence tags in the wrong home count as coverage.
3. **Parallel instruments in one tree.** Abstract vs body; contract vs annex
   that is legally a separate information delivery; policy PDF that concatenates
   entity-level and process-level descriptions. One tag in the bundle is
   existential coverage of the bundle.
4. **Iterated slots.** One complete schedule hides empty sibling schedules; one
   SOX process with a cutoff control hides a sibling process with none; one
   trial arm with harms reporting hides an arm without.
5. **Imprecise coverage.** Analogous to AS 2201.23’s weak ELC: a tag on a
   decorative or off-home node (`attach_to` ignored) is enough to skip close.
   The miss is then silent. Defect will not run either, unless that off-home
   node is itself judged, because fragment judge keys off tags **on the current
   node**.
6. **Form of the function.** Flow diagram required, only narrative counts
   present; written form required, only an email thread is tagged.

None of these is “we should have closed on the sentence that lacked the
function.” In (1)–(3) and (5) the sentence *without* the function is almost
every sentence. The miss is that close’s universe was too large, or that
`covered()` accepted the wrong witness.

## 9. When fragment-level close creates false positives

These are the true positives of the current prohibition.

1. **Open-world local observation.** `¬Instantiates(sentence, purposes)` is the
   normal state of a controller-identity sentence. Close there asserts a
   document gap that has not been evidenced.
2. **Cross-section checklist items.** CONSORT/PRISMA items scored inside the
   wrong section: Methods missing the title identifier; Results missing
   protocol registration; Introduction missing participant-flow numbers.
3. **Legal neighbourhood errors.** Remuneration clause “missing notice”;
   parties block “missing Art. 28 audit”; each recital missing the rest of the
   mandatory set.
4. **Narrative functions.** Story-pack `conflict` / `resolution`: every
   opening sentence would close-miss conflict. The pack already closes
   `conflict` at document, which is the only scale at which “this story has no
   conflict” is a property.
5. **SOX category errors.** Testing a payroll transaction for absence of the
   code of ethics; testing an ITGC narrative sentence for absence of
   order-to-cash cutoff.
6. **Naming conservatism amplifies the flood.** If scan 1 under-tags, document
   close still asks once per missing function. Fragment close asks once per
   (node × missing function). A 200-sentence employment contract with 12
   mandatory functions and conservative naming is thousands of `missing`
   verdicts, almost all type-wrong.
7. **Double counting against defect.** Fragment close on a node that later
   gets the tag on a sibling produces both a local `missing` and a later
   document `keep`, with no reconciliation story except “the other paragraph
   had it.” Current close never emits that contradiction.

The fused-path prompt contract already knew this: fragment source “does not
establish document-wide absence.” Pack close is the same epistemic rule with a
tag map instead of an LLM `missing_elements` list. Moving close down the plant
would reintroduce the bug 0.23/0.24 just named.

## 10. Argument for the current rule

1. **Type of the predicate.** `function_absent` as implemented is `¬∃ n.
   Instantiates(n, F)` over the named population. Its evidence is the inverted
   tag map. That evidence exists only after scan 1 has finished every node the
   pipeline names. Document scope is when that map is complete. Sentence scope
   is when it is not.
2. **Independent practice.** PRISMA E&E’s non-prescriptive location rule, GDPR
   Art. 13/28 set completeness, employment-information obligations that may be
   split across documents, EQUATOR’s “whole report” for CONSORT, and SOX
   completeness as an account assertion all treat presence as a property of an
   instrument or population. They do not treat silence in a part as absence
   from the whole.
3. **Separation from defect.** Once `Covered(F)`, quality belongs on the tagged
   nodes (`defect`). Mixing absence into fragment judge collapses a present
   defective clause into “missing,” which is the wrong legal and reporting
   outcome (you cannot insert what is already there; you change it).
4. **Host sitko stays host work.** Gaps as set difference on `covered()` are
   deterministic, ontology-closed, and free of model prose. Fragment close
   would push gap detection back into per-node verdicts and re-create
   `missing_elements`.
5. **Cost and noise.** One noul per uncovered function at document scope is
   the cheapest sound test. Fragment close is `O(|nodes| × |functions|)`.
6. **Aligns with cascade order.** Post-order scan names leaves first; the
   document node is the first time the inverted map is a closed-world for that
   tree. That is not an accident of API shape.

## 11. Argument against the current rule (as a complete completeness story)

1. **Existential coverage is the wrong operator for located obligations.**
   Title identifiers, IMRaD headings, and rare form-and-locus legal
   requirements are completeness gaps after `Covered(F)` is already true. The
   current rule cannot emit them as `function_absent` without lying about the
   predicate, and it does not emit them any other way.
2. **`attach_to` is currently decorative.** A function declared to attach to
   `section` can be witnessed by a sentence tag. Located completeness cannot
   even be approximated from the pack as written.
3. **Iterated slots are in the plant and invisible to close.** Sibling
   sections, annexes, and schedules are first-class nodes. Close never asks
   “does this section’s subtree instantiate `F`?” SOX process-level precision
   and multi-schedule contracts need that question.
4. **Wrong-home witnesses fail closed in the wrong direction.** A single bad
   tag suppresses the only absence check. Naming errors therefore have
   asymmetric cost: false-negative tags cause extra document closes (noisy but
   visible); false-positive tags hide real gaps (silent). Located close on the
   declared home would not let a header slogan kill a purposes gap.
5. **Parallel completeness universes.** Abstract and title are not “the
   document node.” Treating them as fragments of body review under-detects
   checklist items that those fields alone must carry.
6. **Human completeness audits already go mid-hierarchy.** CONSORT page
   numbers, RCM process rows, walkthrough points, journal section checklists.
   Document-only close matches the *item inventory* of those audits, not their
   *placement* checks. If ReviewKit claims hierarchical review, completeness
   that can only fire at the root is the odd layer out.

These objections do not rescue fragment `CloseRule`. They say the engine has
one completeness operator and the fields have three.

## 12. Verdict

Keep document-only `CloseRule` / `function_absent` for the predicate it
implements. Do not run that predicate at sentence or paragraph. The comparison
fields agree: local silence is not global absence; fragment close is how
checklists get misapplied.

Do not pretend that operator is all of completeness. Located and iterated
absence are real, they are detected mid-hierarchy in every field above, and
document-only close misses them. The next completeness operator, if any, is a
**declared universe** (document default; optional home node / each slot of a
kind), consuming the same `covered()` map filtered to that universe — not a
sentence `when=function_absent`.

Until a second operator exists, hosts that need placement or per-slot gaps
should compute them from `covered()` (node ids already carry plant identity)
rather than ask ReviewKit to contradict its own closed-world rule. That is
sitko, not a fragment close.

## Sources

- Hopewell S, et al. CONSORT 2025 statement: updated guideline for reporting
  randomised trials. Simultaneously published 2025 in *BMJ*, *JAMA*, *Lancet*,
  *Nat Med*, *PLOS Med*. EQUATOR Network record (applies to the whole report).
  Checklist structure: Title and abstract; Open science; Introduction; Methods;
  Results; Discussion. Item 1a: identification as a randomised trial (title).
- Page MJ, et al. The PRISMA 2020 statement. *PLOS Med* / *BMJ*, 2021. PRISMA
  2020 explanation and elaboration: location template “should not be seen as
  prescriptive”; essential elements in the main report or as supplementary
  material.
- Regulation (EU) 2016/679, Art. 13 (information to be provided to the data
  subject) and Art. 28(3) (processor contract shall stipulate a listed set).
- Directive (EU) 2019/1152 on transparent and predictable working conditions;
  Nachweisgesetz (DE); Royal Decree 723/2026 (ES), including residual
  information in additional written documents.
- CASRAI, “IMRaD Structure”: four-section jobs; wrong-section content as
  structural defect even when headings exist.
- PCAOB AS 2201, especially .21 (top-down), .22–.24 (entity-level controls and
  precision), .28 (relevant assertions including completeness), .37–.41
  (walkthroughs; not every labelled control). SOX 404 risk-and-control matrix
  practice as account × assertion × process, not sentence × policy phrase.
- ReviewKit 0.24 host contract: `docs/host-integration.md`, `Pack` rule
  validators (`close` document-only; `defect`/`label` fragment-only),
  `ReviewState.covered()`, `judge_rules` dropping `function_absent` off the
  document node.

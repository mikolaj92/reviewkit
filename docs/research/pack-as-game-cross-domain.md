# Pack as game, cross-domain

Research note. Not a host-integration guide (that is
[`docs/host-integration.md`](../host-integration.md)) and not a product Pack.
ReviewKit 0.24 already ships the schema; this note asks whether that schema is
the right place to put statutes, methods checklists, journal guidelines, and
IRB protocols — or whether stuffing those texts into `instructions.md` is
enough — and how commercial legal AI and scholarly screening tools encode the
same kind of object.

**Claim.** A Pack is the *game* a review plays: an ontology of functions, a
set of source units, and rules as data. A profile is the *reviewer's
behaviour*. The game is portable across Polish law and scientific review. The
instance (function ids, unit text, `force`) is not. Four failure modes kill
the split: a Pack that is too thin, a Pack that becomes a domain dump, a
profile that leaks domain, and a host that computes `covered()` gaps wrong.

This library stays the document-review engine. Domain Packs are host data.
Composition stays at the host / Fala boundary.

## 1. What 0.24 already locked

From `src/reviewkit/pack.py`:

> Pack: the game a review plays. The profile stays the reviewer's behavior.
> A pack is a separate object from instructions.md, external_review_context,
> and profile.toml. The ontology names functions; it holds no source text and
> no obligation. Units hold source text. A rule points at one function and,
> when it needs a source, at one unit.

| Object | Contains | Must not contain |
| --- | --- | --- |
| `Pack` | `Ontology` (function dictionary), `SourceUnit`s, `Rule`s | Reviewer tone, action policy, pipeline |
| `ReviewProfile` | Role, language, document type, pipeline, action policy | Acts, function ids, source text |
| `DecisionClient` | Host plugin for name + judge | A ReviewKit-owned model |
| `LLMClient` | Host plugin for replacement text | Naming or judging on a Pack path |

The play:

1. **Name** every enabled sentence, paragraph, section, and document against
   the whole ontology. `NamingResponse` is `{tags}` only.
2. **Judge** matching `when` / `scope` rules, each with at most the one
   `SourceUnit` it cites. Fragment: `defect`. Document: `close` /
   `function_absent` only when `covered()` has no nodes for that function.
3. **Act** (optional) through `LLMClient` for `change` / `delete` / `insert`
   above the profile confidence floor.

Host gaps:

```text
gaps = pack.ontology.function_ids() − set(state.covered())
```

`ReviewState.covered()` is a presence map: function id → node ids that were
*named* with it. It is not quality, not `missing_elements`, and not
`ReviewFinding.dimension`.

The engine already forbids several bad shapes: a rule that cites an unknown
function or unit; a `close` rule on a fragment; a `label` / `defect` rule on
the document; extra fields on `NamingResponse`. It does **not** forbid a
two-function ontology for a thirteen-item statute, a unit whose `text` is the
entire GDPR, or an `instructions.md` that restates the Pack. Those are host
failures. This note is about them.

## 2. Why stuffing statutes and methods into `instructions.md` fails

The pre-0.24 profile folder could look like a Pack substitute:

```text
profiles/employment-contract.lawyer/
  profile.toml
  instructions.md
  required-clauses.md     # was a Pack substitute; removed in 0.24 docs
  risky-clauses.md
```

`ReviewProfile.instructions_text` concatenates `review_instructions` and every
`*.md` in the folder into one prompt blob. That is a reasonable place for
"escalate one-sided clauses to a person." It is a bad place for Art. 13 RODO
or CONSORT item 7a.

| Need | Pack as data | Stuffing into `instructions.md` |
| --- | --- | --- |
| Address a function | `Function.id` is a stable key | A paragraph in a markdown file has no id |
| Cite one source | `Rule.source_unit_id` → one `SourceUnit` | The model sees the whole blob every node |
| Distinguish binding from commentary | `SourceUnit.force` | Free prose; the model guesses weight |
| Presence vs quality | Name, then `covered()`, then `close` / `defect` | One fused "what's missing / what's wrong" |
| Version a source | Swap a unit (CONSORT 2010 → 2025; EDPB WP260 → current) | Edit a prompt; diffs mix tone and law |
| Audit a finding | Verdict carries `function_id`; unit has `locator` | "The model mentioned Art. 13" |
| Two domains, one engine | Swap the Pack, keep the profile | Duplicate profiles that leak domain |
| Fail closed on absence | Document-scope `close` when `covered()` is empty | Absence judged per sentence, or not at all |
| Keep the fused path honest | `pack=None` is explicit legacy | Domain in markdown silently becomes the game |

The fused `pack=None` path still feeds profile markdown into one
`complete_json` per node. A host that puts Art. 13 into `instructions.md` and
then also passes a Pack has two sources of truth. A host that only stuffs
markdown never gets `covered()`. Either way the engine cannot tell a function
from a tone instruction.

0.24 already rewrote the example profiles to say this in the first paragraph:
behaviour, not Pack. Product docs and `examples/` must not contain `RODO`,
`PKE`, or `UODO` (`tests/test_docs_pack_canon.py`). Domain belongs here, in
host Packs, or in fixtures that are *labelled as thin test doubles*.

## 3. How commercial legal AI encodes checklists

Commercial tools do not publish a Pack schema. They encode the same *job*
(preferred positions, fallbacks, cited sources, coverage) in four families.
None of them is a two-scan review engine with host-owned ontology + units +
rules, but the families map cleanly onto Pack pieces — and onto the failure
modes in §7.

### 3.1 Prompt-shaped playbooks

Early generative legal review: paste the playbook, the statute, or the firm's
PDF into the system prompt and ask for findings. That is `instructions.md`
at product scale. It drafts well and cites poorly. Coverage is "did the model
mention it?", not `ontology − covered()`. Harvey's 2026 playbook-builder
write-up is explicit that this is the thing they are leaving: "Most tools
treat a playbook as static configuration with a form you fill in, one rule at
a time" is the *structured* competitor; the unstructured competitor is a
shared-drive PDF plus a prompt.

### 3.2 Structured playbook records (closest commercial analog)

Harvey Playbook Builder (August 2026) and Spellbook Playbooks encode:

- a contract-type scope (MSA vs NDA — a Pack identity, not a profile);
- per-clause preferred / fallback / walk-away language (clause library ⊆
  units, positions ⊆ defect rules);
- actions, conditions, escalation paths (profile `action_policy` + host
  routing — Harvey's example: flag nonstandard breach-notification for
  privacy counsel rather than auto-redline);
- citations to the source documents behind each rule (units with locators);
- coverage-gap surfacing *while authoring* the playbook (ontology
  completeness, not `covered()` on a document).

Spellbook's public recipe is the three-position framework (preferred,
fallback, non-negotiable) plus an escalation protocol, loaded as "playbook
rules" that fire inside Word ([How to Create a Contract Playbook](https://spellbook.com/learn/how-to-create-a-contract-playbook)).
A stored playbook PDF in a shared drive is the failure mode they sell
against.

What they fuse that Pack splits: name, judge, and act are one pass. There is
usually no public function dictionary separate from the rules, and no
document-scope close computed from a tag map. A Pack host that copies
Harvey's fused "flag + redline + escalate" into `instructions.md` has bought
the commercial UX and thrown away `covered()`.

### 3.3 Trained clause ontologies

Kira (now Litera) shipped 1,400+ clause models across 40+ categories. That is
an ontology of *extractable clause types*, learned, not a host JSON file.
Luminance's anomaly detection is a cousin: name unusual terms, then score
severity. These tools are strong at scan 1 (naming) and weak at scan 2
against a cited source unit: the "source" is the training set, not Art. 13
ust. 1 lit. a. A Pack that tries to be Kira — hundreds of functions, no units
— is the "too thin on sources" variant of §7.1.

### 3.4 CLM obligation graphs

Icertis, Ironclad, Evisort, LinkSquares store post-signature obligations,
clause libraries, and risk scores. That is a different game (lifecycle, not
document review). Reusing a CLM clause library as Pack units is legitimate
*if* each unit still has a locator and a `force`, and rules still cite one
unit. Dumping the CLM corpus into one unit is §7.2.

### 3.5 What they all skip

No major commercial legal AI, as of 2026 public docs, exposes:

- a host-owned function dictionary whose ids are the gap API;
- a hard "at most one cited unit per rule" injection;
- a document-only absence judgement from a tag map;
- a profile that is forbidden to carry the playbook.

Those four are the ReviewKit/host split. Commercial tools encode checklists
as *product configuration*. Pack encodes them as *data the engine can check*.

## 4. How scholarly tools encode checklists

Scientific review already has the Pack job under other names: reporting
guidelines, journal instructions, IRB protocol items. The encodings are more
honest about presence/absence than commercial legal AI, and more likely to
hardcode the ontology in the product.

### 4.1 Presence detectors (name + close, weak defect)

[SciScore](https://www.sciscore.com/) scores methods sections against NIH,
MDAR, and ARRIVE criteria. It names resources (antibodies, cell lines,
organisms) and rigor items (blinding, randomisation, power), then reports
what is missing. The MDAR report is the closest published analog of
`ontology.function_ids() − covered()`. SciScore's own FAQ is the "Pack too
thin" warning in the wild: the generated MDAR report currently detects about
80% of MDAR criteria; the rest is a silent gap if a journal treats the score
as completeness.

[Penelope.ai](https://penelope.ai/) runs 30+ configurable checks per journal:
ethics board named, informed consent, CONSORT/PRISMA abstract subheadings,
required headings, citation/reference bijection, word counts. That is a Pack
per journal. The ontology is the check catalogue; journal guidelines are
units; "critical vs advisory" is `force` or profile policy. Penelope is
explicit that checks are linked to marked-up sections — locators — and that
the journal configures which checks run. It does not give the journal a
three-file Pack to version in git; the catalogue lives in the product.

### 4.2 Deterministic defect against a local unit

[`statcheck`](https://github.com/MicheleNuijten/statcheck) (Nuijten) is a
defect rule, not an ontology. It finds APA-style NHST reports, recomputes
*p*, and flags inconsistency. There is no "sample size justification"
function and no document-scope close. A methods Pack should keep this shape
as a `defect` rule on `function_present` for a `numeric_claim` (or similar)
function, citing a unit that states the reporting convention — not as a
prompt that says "check the statistics."

### 4.3 Author-filled checklists (units without a game)

EQUATOR checklists (CONSORT 2025, SPIRIT 2025, PRISMA, ARRIVE, STROBE) are
still mostly Word/PDF tables the author ticks, with a page/section reference.
[reportilo](https://choxos.github.io/reportilo/) extracts a machine-readable
item list (hand-verified core: PRISMA 2020, CONSORT, STROBE; the rest
best-effort with a parse-confidence score). That is a SourceUnit factory with
an honesty field. It is not a review engine. A host that imports reportilo
items as functions + units, then runs two scans, is using Pack as intended.
A host that pastes the CONSORT PDF into `instructions.md` is not.

CONSORT 2025 is a 30-item checklist plus an expanded bullet-point elicitation
(Hopewell et al., *BMJ* 2025; e081123). SPIRIT 2025 is the protocol-side
twin. PRISMA's 2026 line of work adds a JSON representation of the flow
diagram so the figure is regenerable from data — machine-readable *output*,
still not a review game.

### 4.4 Machine-actionable schemas (heavier than Pack)

FAIRsharing MIRcat publishes JSON Schema + JSON-LD for minimum-information
checklists (MIACA, MIACME, MIFlowCyt, MINSEQE, MIAPPE, …) because narrative
guidelines cannot be validated ([Sansone et al., *Scientific Data*
2022](https://www.nature.com/articles/s41597-022-01707-6)). ICH M11 CeSHarP
(Step 4, 2025) and CDISC USDM do the same for clinical protocols: a template
plus a technical specification with cardinality and conformance, not a
prompt. Those schemas are *authoring and exchange* models. A Pack for IRB /
protocol review should *cite* them as units, not reimplement USDM inside
ReviewKit.

### 4.5 Mapping

| Scholarly object | Pack object | Scan |
| --- | --- | --- |
| CONSORT / SPIRIT / ARRIVE / MDAR item | `Function` | Name |
| Item text + E&E paragraph | `SourceUnit` (`force=binding` or `guidance`) | Judge cites one |
| "Item must appear somewhere" | `close` / `function_absent` @ document | Scan 2 |
| "Item is present but incomplete" | `defect` / `function_present` @ fragment | Scan 2 |
| Journal required heading | `Function` in a *journal* Pack | Name + close |
| RRID / APA statistic | `defect` on a named resource/claim | Scan 2 |
| SciScore "we don't detect this yet" | Missing function in the ontology | §7.1 |
| Author-ticked EQUATOR table | External `covered()` claim; not a substitute for naming | Host lie if trusted blindly |

## 5. Computational-law stack vs Pack

Legal informatics already has a three-layer picture that Pack is a *review*
projection of, not a replacement for (Robaldo, Bartolini, Lenzini, LREC
2020, DAPRECO; Palmirani et al., PrOnto):

```text
Akoma Ntoso / LegalDocML / ELI   structure of the act (locator)
        ↓
Ontology (PrOnto, ELI-PL, Lynx)  concepts
        ↓
LegalRuleML / I/O logic          obligations, permissions, constitutive rules
```

DAPRECO encodes the GDPR as 966 reified I/O formulae (271 obligations, 76
permissions, 619 constitutive) in LegalRuleML, each tied to an Akoma Ntoso
structural index. PrOnto (OWL2-DL) names the concepts; it does not by itself
say what is obligatory. Polish ELI (`eli.gov.pl`, ontology `elipl`) publishes
act metadata as RDF, not the deontic content of Art. 13.

Pack is thinner on purpose:

| Computational-law layer | Pack | Why not more |
| --- | --- | --- |
| Akoma Ntoso / ELI fragment | `SourceUnit.locator` + `source_id` + `text` | Review cites; it does not store the corpus |
| PrOnto class | `Function.id` / `label` | Functions are *reviewable presence*, not a DL TBox |
| LegalRuleML obligation | `Rule` `kind=close` or `defect` + `when` | No defeasible I/O engine in ReviewKit |
| Permission / constitutive | Usually not a review rule | A notice review asks "is this information present and well-formed?", not "is processing lawful?" |

A host that dumps DAPRECO into `units` and asks the LLM to "apply the GDPR"
has rebuilt prompt-stuffing with extra XML. A host that *projects* Art. 13
ust. 1–2 into one function per information item, one unit per locator, and
close/defect rules, is using Pack as a sitko over the statute — the same
shape as a CONSORT Pack over a methods paper.

ReviewKit must not grow a LegalRuleML interpreter. That would be a domain
engine inside the document host.

## 6. Two domains, one game

The sketches below are research illustrations. They are **not** shippable
Packs and they must not be copied into `examples/` (product canon forbids
domain tokens there). The test fixture `tests/fixtures/notice.pack.json` is a
*thin* double (two functions) — see §7.1.

### 6.1 Polish law: information notice (RODO + national DPA + UODO)

The document under review is a klauzula informacyjna / privacy notice. The
binding information list is Art. 13 (collection from the data subject) or
Art. 14 (other sources) of the GDPR, applied as RODO. National overlay:
Ustawa z dnia 10 maja 2018 r. o ochronie danych osobowych; UODO training
still contrasts the old Art. 24 list with the Art. 13 list
([Obowiązek informacyjny, UODO](https://www.uodo.gov.pl/pl/file/7762)).
Commentary overlay: EDPB (ex WP29) transparency guidelines — layered notices,
plain language, Art. 12; UODO emphasises Prezes UODO as the supervisory
authority, not a generic "supervisory authority."

**Ontology (functions are information items, not "the GDPR").** A notice Pack
that is not thin has on the order of Art. 13(1)(a)–(f) + Art. 13(2)(a)–(f),
plus Art. 14 extras (categories of data, source), plus conditionals
(DPO, legitimate interests, third-country transfers, automated decisions)
that `when` can skip. Illustrative ids:

```text
controller_identity          Art. 13(1)(a)
dpo_contact                  Art. 13(1)(b)   # conditional
purposes_and_legal_basis     Art. 13(1)(c)
legitimate_interests         Art. 13(1)(d)   # conditional
recipients                   Art. 13(1)(e)
third_country_transfers      Art. 13(1)(f)   # conditional
retention                    Art. 13(2)(a)
data_subject_rights          Art. 13(2)(b)
withdraw_consent             Art. 13(2)(c)   # conditional
complaint_to_authority       Art. 13(2)(d)   # Polish: Prezes UODO
obligation_to_provide        Art. 13(2)(e)
automated_decisions          Art. 13(2)(f)   # conditional
categories_of_data           Art. 14(1)(d)   # Art. 14 pack only
source_of_data               Art. 14(2)(f)   # Art. 14 pack only
```

**Units (one locator each, `force` is data).**

| `id` | `locator` | `force` | Role |
| --- | --- | --- | --- |
| `rodo-13-1-a` | GDPR Art. 13(1)(a) / ELI or Akoma index | `binding` | Identity of the controller |
| `uodo-complaint` | UODO guidance on Art. 13(2)(d) | `binding` or `guidance` | Name Prezes UODO, not "a DPA" |
| `edpb-layered` | EDPB WP260 rev.01 layered-notice | `guidance` | Defect: wall of text that hides purposes |
| `rodo-13-whole` | "Art. 13" | — | **Forbidden as the only unit** (§7.2) |

**Rules.** Every function: `label` @ fragment / `always`. Every mandatory
function: `close` @ document / `function_absent` citing the binding unit.
Every named occurrence: `defect` @ fragment / `function_present` citing the
same unit (wrong or incomplete statement). Conditional functions: `close`
only `when` the host has already named a trigger (legal basis = legitimate
interests → `legitimate_interests` must be covered). Art. 12 plain language
is a `defect` on whichever function is present, not a thirteenth "style"
function unless the host wants it in `covered()`.

**Profile (behaviour only).** Language `pl`, role "reviewer of notices",
escalate legal-sense changes to a person. Not the Art. 13 list.

The employment-contract example profile after 0.24 already models this
split: "To jest zachowanie recenzenta (JAK), nie Pack (W CO)." A Polish-law
host that puts the Art. 13 list back into that file has undone the release.

### 6.2 Scientific: methods, journal guidelines, IRB protocols

Three related games, same schema.

**Methods paper (CONSORT 2025 / ARRIVE / MDAR).** Functions are checklist
items (`randomisation_method`, `sample_size_justification`,
`blinding`, `outcome_definition`, `participant_flow`, …). Units are the
checklist item + the explanation-and-elaboration paragraph (`force=binding`
for the item, `guidance` for E&E). `close` fires if the paper never names
the item. `defect` fires if the named paragraph is present but does not
satisfy the item (CONSORT 2025 expanded bullets are the defect criterion).
SciScore's resource/RRID checks are extra functions with `defect` against a
unit that requires vendor + catalogue + RRID.

Versioning is a Pack identity, not a profile flag: CONSORT 2010 vs 2025 is
two Packs (or two unit sets). Journals that still say "CONSORT 2010" in
author instructions are running a different game.

**Journal guidelines (Penelope shape).** Functions are required headings,
ethics statement, COI, data sharing, abstract structure, citation style.
Units are the journal's instructions to authors (`locator` = section URL or
PDF page). A *Nature* Pack and a *Addiction* Pack share ReviewKit and do not
share ontologies. Putting "follow CONSORT and name the ethics board" in a
generic `instructions.md` makes every journal the same game.

**IRB / protocol (SPIRIT 2025, ICH M11, local bioethics).** Functions are
SPIRIT items and, where the committee requires them, 45 CFR 46.111-style
approval criteria (risk/benefit, consent, equity) or the Polish komisja
bioetyczna overlay. Units: SPIRIT item text (`binding` as reporting
completeness), ICH M11 template field (`binding` as structure),
institutional SOP (`binding` locally), national statute (`binding`). ICH M11
/ CDISC USDM remain the exchange model for the protocol *file*; Pack is how
a reviewer names and judges a narrative protocol that has not been born as
USDM JSON. An IRB Pack that has three functions ("ethics", "consent",
"risks") is SciScore's 80% MDAR problem under another name.

### 6.3 Side by side

| Pack slot | Polish notice | Methods paper | IRB protocol |
| --- | --- | --- | --- |
| Function | Art. 13 information item | CONSORT/ARRIVE/MDAR item | SPIRIT item / approval criterion |
| Unit | Article point, UODO, EDPB | Checklist item + E&E | SPIRIT, M11 field, SOP, statute |
| `label` | Always, every fragment | Always, every fragment | Always, every fragment |
| `defect` | Named item is wrong/incomplete | Named item fails expanded bullets | Named item fails criterion |
| `close` | Mandatory item never named | Item never named | Item never named |
| Conditional | DPO, transfers, Art. 22 | Harms if intervention has harms | Assent if minors |
| Profile | Language, escalate legal sense | Language, do not rewrite results | Language, do not invent consent |
| Host gap API | `function_ids − covered()` | same | same |

The ontology does not have to be about law. It has to be about *things that
can be present or absent in a document*. That is the portability result.

## 7. Are ontology + rules portable across domains?

**Portable (the game).**

- The triple `Ontology` + `SourceUnit` + `Rule`.
- Function as a namable presence, not a DL class and not a prompt paragraph.
- `Rule.kind` ∈ {`label`, `defect`, `close`}, `scope` ∈ {`fragment`,
  `document`}, `when` ∈ {`always`, `function_present`, `function_absent`}.
- Two scans and host gaps from `covered()`.
- At most one cited unit per judge call (`cited_unit`).
- `SourceUnit.force` as data (`binding`, `dead`, …).
- Profile as behaviour that can be reused under a different Pack.

A CONSORT `close` rule is the same object as an Art. 13 `close` rule. The
engine does not know which domain it is in. That is a feature: ReviewKit
stays an engine.

**Not portable (the instance).**

- Function ids and labels (`controller_identity` is not
  `sample_size_justification`).
- Unit text, locators, and `force` (a UODO PDF is not an ARRIVE E&E).
- Conditional `when` graphs (legitimate interests vs "trial has a DMC").
- What "good enough" means on a `defect` (Polish supervisory-authority
  naming vs RRID checksum).
- Which Pack to load (Art. 13 vs Art. 14 vs CONSORT 2025 vs a journal).

A host that reuses a Polish notice ontology on a methods paper, or copies
CONSORT item ids into a notice Pack, has ported the *instance* and called it
architecture. Portability is schema-level. Cross-domain composition is
multiple Packs, optionally multiple Fala journals, not one god-file.

**What commercial and scholarly tools teach about portability.**

Harvey/Spellbook playbooks are *not* portable across domains: an MSA playbook
does not review a CONSORT paper. SciScore *is* portable inside life-science
methods (MDAR as a generic floor, ARRIVE as a mouse-study overlay) and stops
at the journal-heading layer Penelope owns. EQUATOR's whole point is one
checklist per study design. Pack agrees with EQUATOR and disagrees with
"one mega prompt for law and science."

LegalRuleML is portable as a *language* and not as a GDPR instance; Pack
should copy that lesson, not the 966 formulae.

## 8. Attack vectors

Four. Each has an engine invariant (if any), a host duty, a symptom, and a
cross-domain example.

### 8.1 Pack too thin

**Mechanism.** The ontology has fewer functions than the domain's mandatory
items. `gaps = ontology − covered()` is then a lie: empty gaps mean "we
named everything we bothered to list," not "the notice/paper/protocol is
complete."

**Engine.** No completeness check against an external catalogue. Validators
only require `min_length=1` on `functions` and that rules cite known ids.
`tests/fixtures/notice.pack.json` is two functions (`controller_identity`,
`purposes`). That is a valid Pack and a invalid product notice Pack.

**Symptom.** A notice without retention, rights, or complaint-to-UODO reviews
clean. A trial report without the participant-flow item reviews clean if the
Pack never listed it. SciScore's "≈80% of MDAR" is this attack with a
disclaimer; a host without the disclaimer ships it.

**Host duty.** Keep a *manifest* outside ReviewKit: the canonical function
set for this Pack identity (Art. 13(1)–(2), CONSORT 2025's 30 items, SPIRIT
2025, the journal's Penelope-equivalent list). CI: fixture Packs may be
thin; production Packs are diffed against the manifest. Do not treat the
story example Pack (`opening` / `conflict` / `resolution`) as a domain
template.

**Cross-domain.** Thin law Pack: two GDPR concepts from PrOnto, no Art. 13
list. Thin science Pack: "methods" + "ethics" as functions. Thin IRB Pack:
"consent" only.

### 8.2 Pack becomes a domain dump

**Mechanism.** Units stop being *cited excerpts* and become the corpus:
one unit with the full GDPR, the full CONSORT PDF, the full IRB SOP, or a
concatenation of `required-clauses.md`. Rules all cite that blob. Scan 2
then prompt-stuffs the statute/methods text — `instructions.md` by another
name, with a JSON wrapper. Variant: many `force=dead` units shipped "for
provenance" and then injected wholesale because the host dumps `pack.units`
instead of `cited_unit(pack, rule.source_unit_id)`.

The engine's actual injection path is the second form: `judge_rules` +
`cited_unit` pass **at most one** unit into `FragmentDecisionState.unit` /
`DocumentDecisionState.unit`. The dump only happens if the *host plugin* or
a fat Pack authoring tool ignores that.

**Engine.** Forbids unknown unit ids. Does not cap `text` length. Does not
forbid unused units (the notice fixture includes `unused` / `force=dead` on
purpose). Does not require a rule to cite a unit (`source_unit_id` is
optional) — a defect rule with no unit is a vibe check.

**Symptom.** Judge prompts are huge; citations in findings point at "the
GDPR" / "CONSORT"; versioning is impossible; Art. 13 and Art. 22 fights
happen inside one blob. Scholarly analog: pasting the CONSORT E&E book into
one unit so every randomisation sentence is judged against the whole
guideline.

**Host duty.** One unit per locator; one locator per article point / checklist
item / SOP clause. Dead units may exist for provenance and must not enter
`decide()`. Defect/close rules that need a source must cite one. Authoring
linter: unit `text` over a host budget fails CI. Do not reimport DAPRECO,
USDM, or a CLM corpus as a single unit.

**Cross-domain.** Law: `rodo-13-whole`. Science: `consort-2025.pdf`. IRB:
`institutional-handbook.docx`.

### 8.3 Profile leaks domain

**Mechanism.** `instructions.md`, `profile.toml` `review_instructions`, or
`external_review_context` carries acts, function lists, or source text.
Three sub-cases:

1. **Leak only, no Pack.** Fused `pack=None` path. The game lives in
   markdown. No `covered()`, no unit citations, absence judged (or not) per
   node. This is the 0.23 employment-contract shape that 0.24 deleted from
   examples.
2. **Leak plus Pack.** Two sources of truth. Naming uses the ontology;
   judging also sees "wymagane: tożsamość administratora, cele, …" from the
   profile. Disagreements are silent. The model may name extra ids (dropped
   by `accepted_tags`) or refuse to name ids the markdown never mentioned.
3. **Domain in the wrong profile.** A methods profile that still says
   "sprawdź klauzule RODO", or a notice profile that still says "CONSORT
   item 7a." Product canon already forbids `RODO` / `PKE` / `UODO` in
   `examples/` and host-facing docs; a host app can still leak.

**Engine.** Profile markdown is not a Pack and is not consulted as functions.
On the Pack path, naming questions come from `naming_functions(pack, scope)`
(the whole ontology). The leak hurts through the *plugin*: if the host
DecisionClient is an LLM that also receives `profile.instructions_text`,
domain in the profile is back in the prompt.

**Symptom.** Findings that quote profile prose instead of a unit locator;
different results when the same Pack is run under two profiles; fused-path
CLI reviews that look "legal" without a Pack.

**Host duty.** Profiles state behaviour only (the 0.24 example first
paragraph). DecisionClient context for name/judge is node text + cited unit
+ tags, not `instructions.md`. Do not pass `external_review_context` as a
statute cache. Keep domain tokens out of ReviewKit examples; put them in
host Pack repos.

**Cross-domain.** Law leak: Art. 13 list in `instructions.md`. Science leak:
CONSORT pasted into a "paper.reviewer" profile. IRB leak: 45 CFR 46.111 in
the reviewer-role prompt. All three make the profile non-portable, which is
how people then demand a new engine per domain.

### 8.4 Host `covered()` gaps wrong

`covered()` is the sitko. Getting it wrong is a silent miss, not a crash.
The engine computes the map; the host computes gaps; scan 2 uses the map to
decide whether `close` runs.

| Wrong gap | What actually happened | Effect |
| --- | --- | --- |
| `state.missing_elements` | Removed from `ReviewState` / `ReviewResponse` (see pack tests); host-facing docs still name it so stale fused hosts do not reuse it | Not the domain API; AttributeError or a host-side leftover dict |
| `ReviewFinding.dimension` as function id | Verdicts put the kind in `title` and the function id in `description`; `dimension` is not a function id | Gaps wander into findings telemetry |
| Gaps before naming finishes | `covered()` still empty | Every `close` fires; flood of `missing` |
| Treat tagged-but-defective as a gap | `covered()` is presence, not quality | Double-counts defects as absences, or hides absences |
| Treat untagged as a fragment defect | Absence is document `close` | "Missing Art. 13(1)(a)" on every sentence |
| Run `close` at sentence scope | Validator + `judge_rules` refuse | Host that bypasses `judge_rules` invents per-sentence absence |
| Gaps against a thin ontology | §7.1 | Empty gaps, uncovered domain |
| Trust author-ticked EQUATOR / SPIRIT table as `covered()` | Naming never ran | Host lie; SciScore/Penelope exist because ticks lie |
| **False-positive naming** | `accepted_tags` drops *unknown* ids only | A known id tagged on the wrong node fills `covered()`; document `close` is skipped; **silent miss** |
| False-negative naming | Function never tagged | Spurious `missing` and skipped `defect` (no `function_present`) |

False-positive naming is the dangerous one. The engine cannot know that
"We are the controller, X sp. z o.o." is not `retention`. `check_naming`
only proves ids belong to the ontology and that the payload has no findings.
A host that does not audit naming (spot-check, second noul, conservative
threshold) will skip `close` for items the document does not contain.

`DocumentDecisionState` already passes `covered: list[str]` as the node ids
for *one* candidate function. Mixing that list with the ontology-level gap
set, or passing the whole `covered()` dict in as if it were gaps, is a host
bug.

**`Function.attach_to` vs `naming_functions`.** The schema records
`attach_to` (sentence / paragraph / section) but `naming_functions` names
**every** function at sentence, paragraph, section, *and* document. A host
that assumes "we only name what `attach_to` lists" will disagree with the
engine. Either treat `attach_to` as documentation for authors, or filter in
the host before `decide` — do not assume the engine filtered.

**Cross-domain.** Law: naming tags a purposes sentence as
`controller_identity` → complaint-to-UODO never closes. Science: naming
tags a sample-size sentence as `randomisation_method` → CONSORT
randomisation `close` skipped. IRB: naming tags "we obtained consent" in
the cover letter as the consent-process function → SPIRIT consent item
looks covered.

## 9. What this repo must not become

`AGENTS.md`: ReviewKit stays the document-review rendering/engine library
used with Dike. It does not become a product orchestrator and does not
re-implement Argus/Temida flows. Domain engines stay engines; composition
happens at the host/Fala boundary.

Consequences for this research:

- Do not add Polish-law or CONSORT Packs to `examples/` or `src/reviewkit`.
- Do not add a LegalRuleML / USDM / EQUATOR importer to core.
- Do not encode "completeness vs UODO Art. 13 list" as a ReviewKit validator;
  that is a host manifest.
- Multiple Packs and nested Fala journals are the way to run notice +
  contract, or CONSORT + journal + IRB, over the same document family.

The public contract remains: load Pack, inject `DecisionClient`, two scans,
gaps on the host.

## 10. Host recommendations (Temida or any app)

1. **Author Packs as data.** One git object (JSON/JSONL) per Pack identity
   (notice-art-13-pl, consort-2025, spirit-2025, journal-x). Profile folders
   stay behaviour.
2. **Manifest completeness.** A sibling file lists the canonical function
   ids. CI fails production Packs that drift. Fixture Packs stay thin on
   purpose and are not reused as product.
3. **One unit per locator.** Judge path uses `cited_unit` only. Budget unit
   `text`. Keep `dead` units off the wire.
4. **Profile hygiene.** No acts, no function lists, no source excerpts.
   DecisionClient does not receive `instructions_text` as a statute cache.
5. **Gaps only from `covered()`.** After naming. Never `missing_elements`,
   never `dimension`. Presence ≠ quality: `close` for absence, `defect` for
   a bad instance.
6. **Audit naming.** False-positive tags are silent misses. Sample tags;
   require confidence on noul; do not treat author-ticked checklists as the
   tag map.
7. **Version sources in units.** CONSORT 2010 vs 2025, EDPB vs UODO, SPIRIT
   2013 vs 2025 are Pack/unit versions, not prompt edits.
8. **Conditional functions are host extra.** Pack `when` is
   present/absent/always. "If legal basis is 6(1)(f)" is host state or a
   trigger function, not an `instructions.md` paragraph.

## 11. Sources

### ReviewKit (this repo, 0.24)

- `src/reviewkit/pack.py` — Pack as game; `cited_unit`; `judge_rules`;
  `check_naming`
- `src/reviewkit/state.py` — `ReviewState.covered()`
- `src/reviewkit/decision.py` — `DecisionClient`; fragment/document state
- `docs/host-integration.md`, `README.md`, `docs/releases/0.24.0.md`
- `examples/packs/story.json` — behaviour-domain example Pack
- `tests/fixtures/notice.pack.json` — thin test double, not a product notice
- `tests/test_docs_pack_canon.py` — product docs must not leak domain tokens

### Commercial legal AI

- Harvey, "Turn Your Standards Into Stronger Reviews" (Playbook Builder),
  4 Aug 2026, <https://www.harvey.ai/blog/playbook-builder-in-harvey>
- Spellbook, "How to Create a Contract Playbook", 31 Aug 2026,
  <https://spellbook.com/learn/how-to-create-a-contract-playbook>
- Industry matrices (Kira/Litera clause models, Luminance, CLM playbook
  enforcement): e.g. <https://dancumberlandlabs.com/blog/ai-contract-review-software/>,
  <https://agenticcontractreview.com/platforms-compared/>

### Scholarly / methods / IRB

- SciScore (MDAR / ARRIVE / NIH / RRID), <https://www.sciscore.com/>
- Penelope.ai journal checks, <https://penelope.ai/>
- Nuijten, `statcheck`, <https://github.com/MicheleNuijten/statcheck>
- Hopewell et al., CONSORT 2025, *BMJ* 2025;388:e081123
- SPIRIT 2025, EQUATOR,
  <https://www.equator-network.org/reporting-guidelines/spirit-2013-statement-defining-standard-protocol-items-for-clinical-trials/>
- Sansone et al., machine-actionable MI checklists, *Scientific Data* 2022,
  <https://www.nature.com/articles/s41597-022-01707-6>
- FAIRsharing MIRcat, <https://github.com/FAIRsharing/mircat>
- reportilo, <https://choxos.github.io/reportilo/>
- ICH M11 CeSHarP (Step 4, 2025) and CDISC USDM / Digital Data Flow,
  <https://www.cdisc.org/ddf>

### Computational law / Polish overlay

- Robaldo, Bartolini, Lenzini, "The DAPRECO knowledge base: representing the
  GDPR in LegalRuleML", LREC 2020,
  <https://aclanthology.org/2020.lrec-1.698.pdf>
- Palmirani et al., PrOnto (Privacy Ontology), OWL2-DL
- Akoma Ntoso / LegalRuleML tutorial framing,
  <https://github.com/gvdgdo/ulaswet>
- ELI-PL, <https://api.sejm.gov.pl/about_pl.html>, ontology
  `https://eli.gov.pl/resource/ontology/elipl`
- GDPR Art. 13, <https://gdpr-info.eu/art-13-gdpr/>
- UODO, "Obowiązek informacyjny",
  <https://www.uodo.gov.pl/pl/file/7762>
- EDPB (WP29) transparency guidelines — layered notices, Art. 12

## 12. Bottom line

Stuffing statutes and methods into `instructions.md` makes the profile the
game. Commercial legal AI mostly encodes checklists as product playbooks
(structured records or trained clause ontologies) and still fuses name,
judge, and act. Scholarly tools encode them as presence detectors, author
tables, or heavy schemas (MIRcat, ICH M11) and still hardcode the catalogue.
Computational law already split structure / ontology / rules (Akoma Ntoso,
PrOnto, LegalRuleML); Pack is that split cut down to a document-review
sitko, not a reasoner.

Ontology + rules are portable as a *schema*. Polish RODO notices, CONSORT
methods, journal guidelines, and IRB protocols are four instances of the
same game. They are not one Pack. The attacks that matter are a thin
ontology, a dumped corpus, a leaky profile, and a host that cannot subtract
`covered()` from `function_ids()`. ReviewKit should keep refusing to own
those; hosts should keep failing closed on them.

# Scientific paper review (example Pack)

ReviewKit is a **platform**: a document-review engine plus two host-injected
sockets (`DecisionClient`, `LLMClient`). It is not a journal, not a legal
product, and not a domain library.

This page is the meta for one **example Pack**. Legal review lives in a host
such as Temida. Scientific paper review is the same engine with a different
Pack. Neither domain belongs in `src/reviewkit`.

| Surface | Owns | Does not belong in ReviewKit core |
| --- | --- | --- |
| Legal host (Temida) | Legal ontology, source acts, jurisdiction units, label/defect/close rules, model plugins | Statutes, jurisdiction text, a legal engine fork |
| This example | [`examples/packs/scientific_paper.json`](../../examples/packs/scientific_paper.json) | CONSORT/PRISMA/STROBE as Python, journal policy, a “science” module |
| Profile | Reviewer behavior only — [`examples/profiles/scientific.reviewer`](../../examples/profiles/scientific.reviewer) | Function ids, source units, reporting checklists |

Call site (host wires the sockets; this library does not review the paper
itself):

```python
from pathlib import Path

from reviewkit import Pack, load_profile, review_tree

pack = Pack.model_validate_json(
    Path("examples/packs/scientific_paper.json").read_text()
)
profile = load_profile("examples/profiles/scientific.reviewer")
review_tree(document, profile, llm, pack=pack, decision=decision)
gaps = pack.ontology.function_ids() - set(state.covered())
```

A Pack review **requires** `decision=`. Replacement text still goes through
`LLMClient.complete_json`. See [`docs/host-integration.md`](../host-integration.md).

## How peer review maps onto Pack

A journal workflow is host policy over Pack outcomes. ReviewKit verdicts stay
`keep` / `change` / `delete` / `insert` / `missing`. The host (or editor)
reads gaps and defects and decides desk reject vs revision.

```text
name fragments against IMRaD functions
        → judge defect rules on tagged fragments
        → close missing functions once, on the document
        → host maps {gaps, defects} → desk reject | major | minor | accept
```

| Journal move | Pack signal | Typical host reading |
| --- | --- | --- |
| **Desk reject** | Document `close` / `function_absent` on `abstract`, `research_question`, `methods`, or `results` (nothing in `covered()` for that function) | Not a paper yet: no question, no method, no result |
| **Major revision** | Fragment `defect` on `methods` / `results` / `reproducibility` / `citations` (p-hacking, hallucinated refs, claim with no evidence, methods that cannot be repeated) | Structure exists; the science does not hold |
| **Minor revision** | Fragment `defect` on `citations` / `novelty_claim` / `limitations` (citation-needed, overclaim, unstated limit) | Repairable reporting |
| **Accept** | Named functions present; judge returns `keep` | Host still decides; the engine does not accept a paper |

Absence is judged **once**, on the document, from `covered()`. Do not run
“missing Methods” at sentence scope.

## Same ontology shape for any topic

Physics, trials, systematic reviews, CS, and observational work all name the
**same functions**. Topic is not a Function id. A climate paper and a
randomized trial both have an abstract, a question, methods, results, a
novelty claim, and citations. What changes is which `SourceUnit` a rule cites.

Functions in this Pack (IMRaD plus the claims a reviewer actually names):

| `Function.id` | What the namer tags | Typical `attach_to` |
| --- | --- | --- |
| `abstract` | Structured summary of question, method, result | paragraph, section |
| `research_question` | The question or hypothesis under test | sentence, paragraph |
| `related_work` | Prior work the paper positions against | paragraph, section |
| `methods` | Design, data, procedure, analysis plan | paragraph, section |
| `results` | Observed measurements and estimates | sentence, paragraph, section |
| `discussion` | Interpretation bounded by the results | paragraph, section |
| `limitations` | What the design cannot support | sentence, paragraph, section |
| `citations` | In-text cites and bibliography entries | sentence, paragraph |
| `novelty_claim` | “We show / we are first / this proves” | sentence, paragraph |
| `reproducibility` | Enough detail to repeat or audit the work | paragraph, section |

Scan 1 names every sentence, paragraph, section, and document against this
whole dictionary (`naming_functions`). Tags only — no findings, no actions,
not `ReviewFinding.dimension`.

A Pack for a new field does **not** add `climate` or `oncology` to the
ontology. It adds units (guidelines, primers, house style) and rules that
point at these same functions.

## Reporting guidelines are Pack patterns, not core domain

CONSORT, PRISMA, and STROBE are **checklists in `SourceUnit`s**. They are
not Function ids and not Python. A trial host cites the CONSORT unit from a
`methods` defect; a systematic-review host cites PRISMA; an observational
host cites STROBE. The ontology stays IMRaD.

The example Pack stores **sample** items (design, outcomes, selection,
bias) plus official titles and URLs on the unit. It is a pattern: copy the
unit, replace `text` / `url` with the checklist the journal actually uses.
Do not import those strings into `src/reviewkit`.

The judge sees at most the one unit the rule cites. If the study design
does not match the checklist, the plugin returns `keep`.

## Rules: label / defect / close

Unified 0.24 `Rule`: `kind`, `function_id`, `scope`, `when`, optional
`source_unit_id`.

| `kind` | `scope` | `when` | Role in this Pack |
| --- | --- | --- | --- |
| `label` | `fragment` | `always` | Name this function on a fragment (scan 1 dictionary; labels are not judged) |
| `defect` | `fragment` | `function_present` | Integrity check while the function is tagged: provenance, claim–evidence, overclaim, hallucinated refs, p-hacking, reporting-checklist items |
| `close` | `document` | `function_absent` | The paper never named this function (`covered()` empty) |

Validators: `function_id` is in the ontology; `source_unit_id` is in
`units`. Label and defect are fragment-only; close is document-only.

## Units: guidelines, citation integrity, optional primers

`SourceUnit.force` is data (`expectation`, `heuristic`, `recommended`,
`optional`, …), not a profile flag.

1. **Generic IMRaD expectations** — what any topic paper owes the reader
   (question, method that could produce the result, result that matches the
   method, discussion that does not outrun the result).
2. **Reporting-guideline samples** — CONSORT / PRISMA / STROBE-style
   checklists as unit text + URL.
3. **Citation integrity heuristics** — the load-bearing units for
   low-quality and egg papers:
   - **Provenance (what they cite)** — a bibliography is not coverage.
     Each in-text claim must point at a real work that actually contains
     the attributed statement. Name-drops, secondary summaries in place of
     the primary source, and cites that cannot be resolved fail this unit.
   - **Claim–evidence** — a `novelty_claim` or result sentence must link to
     a result, table, figure, or method that could support it.
   - **Citation-needed** — a specific, contestable assertion with no cite.
   - **Overclaim** — causal language from non-causal design; “proves” /
     “first ever” without warrant.
   - **Hallucinated refs** — author/year/title/venue/DOI that do not
     resolve to one work.
   - **P-hacking flags** — undisclosed multiplicity, outcome switching,
     optional stopping, HARKing.
4. **Optional primers** — scientific method and information-theory pointers
   as units (`text` = title, `url` = locator). They are data in the Pack,
   not hardcoded in Python. A host may cite them from a defect or leave
   them uncited for later rules. Use them when the manuscript is
   cargo-cult form with no testable question.

Egg papers usually fail **provenance** and **claim–evidence** first, then
close on `research_question` / `methods` / `reproducibility`. Do not treat
“has a reference list” as `citations` covered in any strong sense: coverage
is that fragments were *named*; integrity is the defect on those fragments.

## Host wiring

```text
Pack load  →  inject DecisionClient  →  name, then judge
                                         → optional LLMClient act
```

- Temida (legal) and a paper-review app are both hosts. They do not share
  ontology ids. They share this library’s Pack schema and sockets.
- Model runtimes stay in the host. Tests and examples use
  `MockDecisionClient` / `MockLLMClient` only.
- `instructions.md` is reviewer tone. Putting IMRaD or CONSORT in the
  profile does not load a Pack.
- Gaps: `pack.ontology.function_ids() - set(state.covered())` on the host.
  `ReviewState.missing_elements` is not that API.

## What this Pack is not

- Not a domain in `src/reviewkit`.
- Not a legal Pack: no statutes, no jurisdiction acts, no privacy-instrument
  functions. Those stay in the legal host.
- Not a model: no runtime, weight name, or server URL in core.
- Not a substitute for an editor. Desk reject / major / minor is host
  policy over Pack traces.

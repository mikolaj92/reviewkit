# Ocena zastąpienia Dike przez ReviewKit

Data analizy: 2026-06-12

Zakres lokalny:

- Dike: `/Users/mini-m4-1/Developer/Temida/dike`
- ReviewKit: `/Users/mini-m4-1/Developer/DocReviewer/reviewkit`

## Wniosek

ReviewKit może zastąpić tę część Dike, która odpowiada za **human-facing review artifact**:

- wczytanie dokumentu DOCX,
- przejście po strukturze dokumentu,
- zebranie działań recenzenckich,
- deterministyczne zastosowanie bezpiecznych zmian,
- wygenerowanie `reviewed.docx` i `corrected.docx`.

ReviewKit nie powinien zastępować wprost całego Dike. Dike ma dużo logiki domenowej i operacyjnej, która powinna zostać źródłem ustaleń albo osobnym krokiem Fali:

- deterministyczna klasyfikacja dokumentów prawnych,
- reguły prawne z YAML,
- findingi z podstawą prawną i evidence refs,
- Mnemozyna grounding,
- fail-closed policy,
- risk scoring,
- compliance reports,
- review packets,
- golden/adversarial corpus,
- audit/cache/batch/history/workflow surfaces.

Najlepszy kierunek: **Dike jako legal finding/rule provider, ReviewKit jako generyczny review engine i renderer DOCX, Fala jako orkiestrator**.

## Co Dike robi dziś

Są dwie warstwy Dike.

### Legacy DOCX review flow

Pliki:

- `src/dike/agent.py`
- `src/dike/document_reader.py`
- `src/dike/processor.py`
- `src/dike/reviewer.py`
- `src/dike/docx_io.py`

Pipeline:

1. `read_docx` czyta DOCX do listy akapitów z tytułem sekcji.
2. `select_document_profile` dobiera profil dokumentu.
3. `process_document` robi dwupasowy paragraph review:
   - najpierw review akapitów z kontekstem sąsiednich akapitów, sekcji i dokumentu,
   - potem agreguje sekcje i dokument,
   - potem ponownie reviewuje akapity z już znanym kontekstem sekcji/dokumentu.
4. `OpenAICompatibleParagraphReviewer` wysyła pojedynczy akapit do LLM-a.
5. Model zwraca `ParagraphAssessment`, między innymi:
   - `assessment`,
   - `issue_type`,
   - `severity`,
   - `confidence`,
   - `requires_human_review`,
   - `action_type`,
   - `issue`,
   - `suggestion`,
   - `legal_note`,
   - `proposed_text`,
   - `apply_to_corrected`.
6. `_apply_correction_policy` decyduje, czy proposed paragraph może trafić do corrected draftu.
7. `write_review_docx` robi DOCX z komentarzami Worda.
8. `write_corrected_docx` robi corrected draft z akapitami, gdzie `apply_to_corrected=True`.

To jest najbliższa część do zastąpienia przez ReviewKit.

### Shipped Dike runtime

Pliki:

- `packages/dike_app/src/dike_app/service.py`
- `packages/dike_app/src/dike_app/rules/`
- `packages/dike_app/src/dike_app/reporting.py`
- `packages/dike_app/src/dike_app/review_packet.py`
- `packages/dike_core/src/dike_core/domain/reports.py`
- `packages/dike_docs/src/dike_docs/parsers/`

Pipeline:

1. ingest,
2. extract DOCX/PDF,
3. classify,
4. evaluate rule engine,
5. report JSON/Markdown.

Ten runtime nie jest tylko edytorem dokumentów. To deterministyczny subsystem compliance/legal review z własnym modelem `ComplianceReport`, `Finding`, `Recommendation`, `EvidenceRef`, `LegalBasisRef`.

## Porównanie z ReviewKit

| Obszar | Dike | ReviewKit dziś | Wniosek |
| --- | --- | --- | --- |
| DOCX input | Tak, legacy i shipped parsers | Tak, podstawowo | ReviewKit potrzebuje lepszych segmentów z locatorami |
| Hierarchia review | Paragraph-first, sekcje/dokument agregowane | Sentence -> paragraph -> section -> document | ReviewKit ma lepszą docelową architekturę review |
| LLM provider | OpenAI-compatible przez gateway | Generyczny `LLMClient` | ReviewKit jest bardziej wymienny |
| Profile | YAML, ale mocno Dike-specific | Folder YAML/Markdown dla ludzi | ReviewKit pasuje do profili reviewerów |
| Grounding prawny | Mnemozyna mandatory dla Dike legacy | Brak | Musi być adapter/context provider |
| Reguły prawne | Tak, config-driven | Brak | Nie przenosić do core ReviewKit |
| Finding model | Bogaty legal/compliance model | Generyczny `ReviewAction` | Potrzebny mapper Finding -> ReviewAction |
| Corrected policy | Rozbudowana, profile-driven | Prosta apply policy | Trzeba dodać policy hooks/guards |
| Posejdon placeholders | Guard w Dike | Brak | Trzeba dodać guard przed auto-apply |
| Comments | Dike używa komentarzy `python-docx` | ReviewKit używa komentarzy Worda | Zostawić generycznie w core |
| Track Changes | Brak pełnego OpenXML | Tak, `w:ins` / `w:del` w `reviewed.docx` | ReviewKit może być lepszym rendererem review |
| Reports JSON/MD | Tak | Nie taki cel | Nie zastępować przez ReviewKit |
| Batch/cache/audit/history | Tak | Brak | Zostawić w Fali/Dike/Argus |

## Co trzeba dodać do ReviewKit, żeby przejął legacy Dike DOCX review

Minimalny plan:

1. Dodać `ReviewContextProvider` hook:
   - dla sentence/paragraph/section/document,
   - może wstrzyknąć grounding, profile metadata, classifier result, evidence refs.

2. Dodać `ActionPolicy` hook zamiast samego `apply_policy`:
   - status action zależy od category, severity, confidence, human-review flag,
   - możliwość blokady auto-apply przez reguły typu Posejdon placeholder guard.

3. Rozszerzyć `ReviewAction`:
   - `metadata: dict[str, Any]`,
   - `legal_basis`,
   - `evidence_refs`,
   - `source_system`,
   - `policy_reason`.

4. Dodać mapper Dike -> ReviewKit:
   - `ParagraphAssessment` -> `ReviewAction`,
   - `ComplianceReport/Finding` -> `ReviewAction`.

5. Ulepszyć parser DOCX:
   - body, tables, headers, footers, comments, footnotes,
   - stable locator / segment id,
   - wykrywanie tracked revisions.

6. Ulepszyć renderer:
   - Word comments przez `document.comments.add_comment`,
   - reviewed output z komentarzami i propozycjami zmian,
   - corrected output bez nagłówków raportowych, jako czysty skorygowany dokument tam, gdzie to możliwe.

7. Dodać profil `dike.legal-review` albo adapter profilu Dike:
   - Dike YAML może zostać domenowy,
   - ReviewKit profile powinny pozostać human-editable.

## Proponowana architektura Fala/Dike/ReviewKit

Docelowy przepływ:

```text
Fala
  -> intake / anonymization / routing
  -> Dike legal analysis
       -> ComplianceReport / Findings / Evidence / Recommendations
  -> ReviewKit
       -> map findings + LLM/editor review into ReviewAction
       -> render reviewed.docx
       -> render corrected.docx
  -> Argus / operator queue
```

Dike nie powinien pisać finalnych DOCX-ów w przyszłej architekturze. Powinien produkować:

- findings,
- recommendations,
- evidence refs,
- legal basis,
- human-review triggers,
- bounded policy constraints.

ReviewKit powinien produkować:

- `reviewed.docx`,
- `corrected.docx`,
- listę `ReviewAction`,
- statystyki,
- deterministyczny audit aplikacji zmian.

Fala powinna decydować:

- kiedy uruchomić Dike,
- kiedy uruchomić ReviewKit,
- kiedy eskalować do człowieka,
- jak wiązać artefakty z Posejdonem/Argusem.

## Decyzja readiness

ReviewKit może teraz zastąpić około **40-50% legacy Dike DOCX review flow**:

- strukturę przeglądu,
- LLM abstraction,
- statusy akcji,
- corrected/reviewed output,
- komentarze Worda i podstawowe Track Changes,
- ogólny model profili.

ReviewKit nie może jeszcze zastąpić:

- Mnemozyna grounding,
- Dike legal rule engine,
- Dike compliance reports,
- Dike review packets,
- profile-driven corrected policy,
- Posejdon placeholder safety,
- bogatego parsera DOCX/PDF.

Po dodaniu adapterów i policy hooks ReviewKit może przejąć **80-90% legacy Dike DOCX artifact flow**, ale Dike nadal powinien zostać legal/compliance providerem.

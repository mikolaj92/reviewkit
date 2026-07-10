# Ocena zastąpienia Dike przez ReviewKit

> **NIEAKTUALNE (2026-07).** Migracja opisana niżej została wykonana: dike renderuje
> brudnopis i czystopis przez reviewkit (#3319/#3339), a legacy pliki dike, do których
> odwołuje się ta ocena, już nie istnieją. Dokument zostaje jako zapis historyczny.

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
| DOCX input | Tak, legacy i shipped parsers | Tak, body/tabele/header/footer z locatorami + tracked revisions | Pokrycie legacy scope; bogatszy PDF/footnotes opcjonalnie |
| Hierarchia review | Paragraph-first, sekcje/dokument agregowane | Sentence -> paragraph -> section -> document | ReviewKit ma lepszą docelową architekturę review |
| LLM provider | OpenAI-compatible przez gateway | Generyczny `LLMClient` | ReviewKit jest bardziej wymienny |
| Profile | YAML, ale mocno Dike-specific | Folder YAML/Markdown dla ludzi | ReviewKit pasuje do profili reviewerów |
| Grounding prawny | Mnemozyna mandatory dla Dike legacy | Hook `ReviewContextProvider` gotowy, dane zewnętrzne | Podpiąć Mnemozynę jako context provider |
| Reguły prawne | Tak, config-driven | Brak | Nie przenosić do core ReviewKit |
| Finding model | Bogaty legal/compliance model | Generyczny `ReviewAction` + `references`/`metadata`/`evidence_refs` | Potrzebny mapper Finding -> ReviewAction |
| Corrected policy | Rozbudowana, profile-driven | `ActionPolicy` z fail-closed gating | Gotowe w core |
| Posejdon placeholders | Guard w Dike | `protected_patterns` + wstrzykiwalny guard hook | Gotowe w core |
| Comments | Dike używa komentarzy `python-docx` | ReviewKit kotwiczy komentarze na fragmencie | Zostawić generycznie w core |
| Track Changes | Brak pełnego OpenXML | Tak, in-place `w:ins` / `w:del` w `reviewed.docx` | ReviewKit może być lepszym rendererem review |
| Reports JSON/MD | Tak | Nie taki cel | Nie zastępować przez ReviewKit |
| Batch/cache/audit/history | Tak | Brak | Zostawić w Fali/Dike/Argus |

## Co trzeba dodać do ReviewKit, żeby przejął legacy Dike DOCX review

### Zrobione (już w core)

Poniższe punkty pierwotnego minimalnego planu są już zaimplementowane w ReviewKit:

1. `ReviewContextProvider` hook (`reviewkit.context`):
   - działa dla sentence/paragraph/section/document,
   - może wstrzyknąć grounding, profile metadata, classifier result, evidence refs
     jako generyczny `ReviewContext`.

2. `ActionPolicy` zamiast samego `apply_policy` (`reviewkit.policy`,
   `ActionPolicyConfig`):
   - status akcji zależy od category, severity, confidence, priority i human-review flag,
   - fail-closed gating: `require_llm_apply_hint`, `min_confidence_for_auto_apply`,
     `allowed_action_types_for_auto_apply`, `blocked_categories`,
   - blokada auto-apply przez guard typu Posejdon placeholder — generyczne
     `protected_patterns` plus wstrzykiwalny guard hook.

3. Rozszerzony `ReviewAction` (`reviewkit.models`):
   - `metadata: dict[str, Any]`,
   - `evidence_refs`,
   - `source_system`,
   - `policy_reason`,
   - `references` (generyczne odnośniki).
   - `legal_basis` **celowo NIE zostało dodane** jako nazwane pole core. Nazwane
     pole prawne złamałoby kontrakt domeno-/językowej ślepoty core (#2975); podstawa
     prawna jest przenoszona przez generyczne `references`/`metadata`, które mapper
     Dike wypełnia po swojej stronie.

5. Bogatszy parser DOCX (`reviewkit.parser_docx`):
   - stable locator / segment id na body/tabelach/headerach/footerach,
   - wykrywanie tracked revisions (ostrzeżenie w wyniku),
   - tabele lądują pod swoją sekcją autorską, header/footer w dedykowanych sekcjach.

6. Renderer (`reviewkit.renderer_docx`):
   - reviewed output patchowany in-place dla body/tabel/headerów/footerów,
   - Word comments kotwiczone na fragmencie,
   - propozycje zmian jako `w:ins` / `w:del`,
   - corrected output jako czysty skorygowany dokument (kopia oryginału, tylko
     bezpieczne edycje), bez nagłówków raportowych.

### Genuine gaps (do zrobienia poza core)

4. Mapper Dike -> ReviewKit (adapter, poza core, żeby nie wnosić domeny do rdzenia):
   - `ParagraphAssessment` -> `ReviewAction`,
   - `ComplianceReport/Finding` -> `ReviewAction`,
   - wypełnia `references`/`metadata`/`evidence_refs`/`source_system`.

7. Profil `dike.legal-review` albo adapter profilu Dike:
   - Dike YAML może zostać domenowy,
   - ReviewKit profile powinny pozostać human-editable.

8. Pozostałe subsystemy zostają po stronie Dike/Fali (nie przenosić do core):
   - Mnemozyna grounding jako context provider,
   - legal rule engine, compliance reports, review packets,
   - bogatszy parser PDF,
   - batch/cache/audit/history/workflow surfaces.

Rozszerzenie parsera DOCX o comments/footnotes jako źródło wejścia pozostaje
opcjonalnym usprawnieniem, nie warunkiem przejęcia flow.

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

Po zaimplementowaniu context providera, policy hooks, rozszerzonego `ReviewAction`,
bogatszego parsera i renderera (patrz sekcja "Zrobione"), ReviewKit pokrywa już
**~80% legacy Dike DOCX review flow** samym rdzeniem:

- hierarchiczną strukturę przeglądu (sentence -> paragraph -> section -> document),
- LLM abstraction i wstrzykiwalny context provider,
- statusy akcji z fail-closed ActionPolicy (category/severity/confidence/priority,
  apply-hint, protected_patterns + guard hook),
- corrected/reviewed output (in-place `w:ins`/`w:del`, kotwiczone komentarze Worda,
  czysty corrected draft na kopii oryginału),
- wykrywanie tracked revisions,
- human-editable model profili.

Do pełnego przejęcia legacy flow brakuje już tylko warstwy integracyjnej i domenowej,
która **z założenia zostaje poza core** ReviewKit:

- mapper Dike Finding/`ParagraphAssessment` -> `ReviewAction`,
- profil/adapter `dike.legal-review`,
- Mnemozyna grounding podpięta jako context provider.

Dalej po stronie Dike/Fali (nie cel ReviewKit):

- Dike legal rule engine,
- Dike compliance reports,
- Dike review packets,
- bogaty parser PDF,
- batch/cache/audit/history/workflow surfaces.

Po dodaniu mappera i profilu adaptera ReviewKit może przejąć **~90% legacy Dike DOCX
artifact flow**, ale Dike nadal powinien zostać legal/compliance providerem.

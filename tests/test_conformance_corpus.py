"""Domain-conformance corpus for the public ReviewKit pipeline.

The documents and responses below are synthetic test data.  They deliberately keep
one technical shape while varying only the product-owned profile and grounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reviewkit import pipeline


@dataclass(frozen=True)
class CorpusCase:
    name: str
    document: str
    criterion: str
    grounding: str
    local_finding: str
    document_finding: str


CORPUS = (
    CorpusCase(
        "umowa",
        "§ 1. Zapłata nastąpi w 7 dni.\n§ 2. Termin zapłaty wynosi 14 dni.",
        "legal clause consistency",
        "Uzgodniony termin płatności: 14 dni.",
        "Sprzeczny termin płatności w § 1.",
        "Umowa podaje dwa różne terminy płatności.",
    ),
    CorpusCase(
        "rozprawka",
        "Teza: transport publiczny ogranicza korki.\nArgument: autobusy są czerwone.",
        "school thesis and argument",
        "Argument powinien uzasadniać tezę.",
        "Kolor autobusu nie uzasadnia tezy.",
        "Rozprawka nie łączy argumentu z tezą.",
    ),
    CorpusCase(
        "artykul",
        "Miasto otworzyło most w maju.\nOtwarcie całkowicie zlikwidowało korki.",
        "newsroom fact and narrative",
        "Pomiar ruchu wykazał spadek o 8%, nie likwidację korków.",
        "Twierdzenie o likwidacji korków jest niezgodne z pomiarem.",
        "Narracja artykułu wyolbrzymia udokumentowany efekt.",
    ),
    CorpusCase(
        "paper",
        "Badanie objęło 12 próbek.\nWyniki dowodzą skuteczności dla całej populacji.",
        "scientific method and evidence",
        "Próba nie była reprezentatywna dla populacji.",
        "Wniosek wykracza poza badaną próbę.",
        "Dowody nie wspierają uogólnienia w konkluzji.",
    ),
)


class RecordedLLM:
    """Offline response cassette used only by this fixture suite."""

    def __init__(self, case: CorpusCase):
        self.responses = {
            "sentence": [],
            "paragraph": [case.local_finding],
            "section": [],
            "document": [case.document_finding],
        }


@pytest.mark.parametrize("case", CORPUS, ids=lambda case: case.name)
def test_profiles_and_grounding_use_one_public_review_topology(
    case: CorpusCase, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    profile = SimpleNamespace(
        name=case.name,
        criteria=[case.criterion],
        outputs=SimpleNamespace(reviewed_docx=False, corrected_docx=False),
    )
    context = SimpleNamespace(grounding=case.grounding)
    llm = RecordedLLM(case)

    monkeypatch.setattr(pipeline, "load_profile", lambda _: profile)
    monkeypatch.setattr(
        pipeline,
        "load_docx",
        lambda _: SimpleNamespace(metadata={}, text=case.document),
    )

    class RecordingHierarchicalReviewer:
        def __init__(self, **kwargs: Any):
            calls.append(kwargs)

        def review(self, document: Any) -> tuple[list[Any], list[Any], Any]:
            findings = [
                SimpleNamespace(
                    finding_id=f"{case.name}-{scope}",
                    scope=scope,
                    message=message,
                    metadata={},
                )
                for scope, messages in llm.responses.items()
                for message in messages
            ]
            return findings, [], SimpleNamespace(document_summary=case.name, warnings=[])

    monkeypatch.setattr(pipeline, "TaktReviewer", RecordingHierarchicalReviewer)
    monkeypatch.setattr(pipeline, "ReviewResult", SimpleNamespace)
    monkeypatch.setattr(pipeline.ReviewStats, "from_actions", lambda _: SimpleNamespace())

    result = pipeline.review_document(
        tmp_path / f"{case.name}.docx",
        tmp_path / f"{case.name}-profile",
        llm,
        context_provider=context,
    )

    assert pipeline.REVIEW_ENGINE_SCOPES == ("sentence", "paragraph", "section", "document")
    assert calls == [
        {
            "profile": profile,
            "llm": llm,
            "context_provider": context,
            "action_policy": None,
        }
    ]
    assert [finding.scope for finding in result.findings] == ["paragraph", "document"]
    assert [finding.message for finding in result.findings] == [
        case.local_finding,
        case.document_finding,
    ]


def test_core_pipeline_contains_no_domain_dispatch() -> None:
    source = Path(pipeline.__file__).read_text(encoding="utf-8").casefold()

    assert all(word not in source for word in ("legal", "school", "news", "scientific"))

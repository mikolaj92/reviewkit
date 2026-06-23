from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document as DocxDocument

from reviewkit import ReviewResult, parser_docx, review_document
from reviewkit.context import ReviewContext, ReviewContextProvider
from reviewkit.document import ReviewDocument
from reviewkit.llm import MockLLMClient
from reviewkit.models import ActionStatus, ReviewActionType
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def test_hierarchical_review_passes_lower_level_results(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "Ala ma kota.")
    reviewed_path = tmp_path / "reviewed.docx"
    corrected_path = tmp_path / "corrected.docx"
    llm = MockLLMClient(
        responses=[
            {
                "actions": [
                    {
                        "id": "a-sentence",
                        "scope": "sentence",
                        "action_type": "replace",
                        "node_id": "p1.s1",
                        "original_text": "kota",
                        "replacement_text": "psa",
                        "reason": "Zmiana testowa.",
                        "category": "typo",
                        "confidence": 0.9,
                    }
                ],
                "summary": "Zdanie sprawdzone.",
            },
            {
                "actions": [
                    {
                        "id": "a-paragraph",
                        "scope": "paragraph",
                        "action_type": "comment",
                        "node_id": "p1",
                        "comment": "Akapit jest zrozumiały.",
                        "confidence": 0.8,
                    }
                ],
                "summary": "Akapit sprawdzony.",
            },
            {
                "actions": [
                    {
                        "id": "a-section",
                        "scope": "section",
                        "action_type": "summary",
                        "node_id": "s1",
                        "comment": "Sekcja jest krótka.",
                        "confidence": 0.8,
                    }
                ],
                "summary": "Sekcja sprawdzona.",
            },
            {
                "actions": [],
                "summary": "Dokument sprawdzony.",
            },
        ]
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=llm,
        out_reviewed=reviewed_path,
        out_corrected=corrected_path,
    )

    assert len(result.actions) == 3
    assert result.actions[0].status == ActionStatus.APPLIED
    assert result.document_summary == "Dokument sprawdzony."
    assert "sentence_review_results" in llm.calls[1].content
    assert "a-sentence" in llm.calls[1].content
    assert "paragraph_review_results" in llm.calls[2].content
    assert "a-paragraph" in llm.calls[2].content
    assert "section_review_results" in llm.calls[3].content
    assert "a-section" in llm.calls[3].content


def test_sentence_review_adds_action(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "confidence": 1.0,
        },
        text="To jest bład.",
    )

    assert len(result.actions) == 1
    assert result.actions[0].id == "a1"
    assert result.actions[0].action_type == ReviewActionType.REPLACE


def test_applied_actions_are_written_to_corrected_docx(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "confidence": 1.0,
        },
        text="To jest bład.",
    )

    corrected_text = _docx_text(result.corrected_docx)
    assert "błąd" in corrected_text
    assert "bład" not in corrected_text


def test_suggestion_text_edits_are_tracked_in_reviewed_but_not_applied_in_corrected(
    tmp_path: Path,
) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bardzo",
            "replacement_text": "wyjątkowo",
            "category": "style",
            "confidence": 1.0,
        },
        text="To jest bardzo dobre.",
    )

    corrected_text = _docx_text(result.corrected_docx)
    reviewed_comments = _docx_comments(result.reviewed_docx)
    reviewed_xml = _docx_document_xml(result.reviewed_docx)
    assert "[DELETE:" not in reviewed_xml
    assert _revision_texts(result.reviewed_docx, "del", "delText") == ["bardzo"]
    assert _revision_texts(result.reviewed_docx, "ins", "t") == ["wyjątkowo"]
    assert "SUGGESTION" in reviewed_comments
    assert result.actions[0].status == ActionStatus.NOT_APPLIED
    assert "bardzo" in corrected_text
    assert "wyjątkowo" not in corrected_text


def test_conflict_is_not_applied(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "kot",
            "replacement_text": "pies",
            "category": "typo",
            "confidence": 1.0,
        },
        text="kot i kot.",
    )

    corrected_text = _docx_text(result.corrected_docx)
    assert result.actions[0].status == ActionStatus.CONFLICT
    assert "kot i kot." in corrected_text
    assert "pies" not in corrected_text


def test_document_type_action_policy_can_change_review_status(tmp_path: Path) -> None:
    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "replace",
            "node_id": "p1.s1",
            "original_text": "bład",
            "replacement_text": "błąd",
            "category": "typo",
            "severity": "high",
            "confidence": 1.0,
        },
        text="To jest bład.",
    )

    assert result.actions[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert "exceeds policy threshold" in (result.actions[0].policy_reason or "")
    corrected_text = _docx_text(result.corrected_docx)
    assert "bład" in corrected_text
    assert "błąd" not in corrected_text


def test_policy_guard_blocks_corrected_when_protected_placeholder_changes(
    tmp_path: Path,
) -> None:
    input_path = _make_docx(tmp_path, "[OSOBA_1] podpisał umowę.")
    llm = MockLLMClient(
        responses=[
            {
                "actions": [
                    {
                        "id": "a1",
                        "scope": "sentence",
                        "action_type": "replace",
                        "node_id": "p1.s1",
                        "original_text": "[OSOBA_1]",
                        "replacement_text": "Jan Kowalski",
                        "category": "typo",
                        "confidence": 1.0,
                        "apply_to_corrected": True,
                    }
                ],
                "summary": "Zdanie sprawdzone.",
            },
            {"actions": [], "summary": "Akapit sprawdzony."},
            {"actions": [], "summary": "Sekcja sprawdzona."},
            {"actions": [], "summary": "Dokument sprawdzony."},
        ]
    )

    result = review_document(
        input_path=input_path,
        profile_path="examples/profiles/employment-contract.lawyer",
        llm=llm,
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
    )

    assert result.actions[0].status == ActionStatus.NEEDS_HUMAN_DECISION
    assert result.actions[0].metadata["blocked_from_corrected"] is True
    corrected_text = _docx_text(result.corrected_docx)
    assert "[OSOBA_1] podpisał umowę." in corrected_text
    assert "Jan Kowalski" not in corrected_text


def test_context_provider_is_included_in_prompts(tmp_path: Path) -> None:
    input_path = _make_docx(tmp_path, "Ala ma kota.")
    llm = MockLLMClient(
        responses=[
            {"actions": [], "summary": "Zdanie sprawdzone."},
            {"actions": [], "summary": "Akapit sprawdzony."},
            {"actions": [], "summary": "Sekcja sprawdzona."},
            {"actions": [], "summary": "Dokument sprawdzony."},
        ]
    )

    review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=llm,
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
        context_provider=_StaticContextProvider(),
    )

    assert "external_review_context" in llm.calls[0].content
    assert "Dike-style grounding" in llm.calls[0].content


def test_tracked_revision_inputs_are_reported_as_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(parser_docx, "_contains_tracked_revisions", lambda path: True)

    result = _run_with_single_sentence_action(
        tmp_path,
        action={
            "id": "a1",
            "scope": "sentence",
            "action_type": "comment",
            "node_id": "p1.s1",
            "comment": "Sprawdź historię zmian.",
            "confidence": 1.0,
        },
        text="To jest tekst.",
    )

    assert result.warnings == ["Input DOCX contains tracked revisions."]


def _run_with_single_sentence_action(
    tmp_path: Path,
    action: dict[str, Any],
    text: str,
) -> ReviewResult:
    input_path = _make_docx(tmp_path, text)
    llm = MockLLMClient(
        responses=[
            {"actions": [action], "summary": "Zdanie sprawdzone."},
            {"actions": [], "summary": "Akapit sprawdzony."},
            {"actions": [], "summary": "Sekcja sprawdzona."},
            {"actions": [], "summary": "Dokument sprawdzony."},
        ]
    )
    return review_document(
        input_path=input_path,
        profile_path="examples/profiles/story.teacher",
        llm=llm,
        out_reviewed=tmp_path / "reviewed.docx",
        out_corrected=tmp_path / "corrected.docx",
    )


def _make_docx(tmp_path: Path, text: str) -> Path:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph(text)
    docx.save(input_path)
    return input_path


def _docx_text(path: Path | None) -> str:
    assert path is not None
    docx = DocxDocument(str(path))
    return "\n".join(paragraph.text for paragraph in docx.paragraphs)


def _docx_comments(path: Path | None) -> str:
    assert path is not None
    docx = DocxDocument(str(path))
    return "\n".join(comment.text for comment in docx.comments)


def _docx_document_xml(path: Path | None) -> str:
    assert path is not None
    with ZipFile(path) as archive:
        return archive.read("word/document.xml").decode()


def _revision_texts(path: Path | None, revision_tag: str, text_tag: str) -> list[str]:
    root = ElementTree.fromstring(_docx_document_xml(path))
    return [
        "".join(element.itertext())
        for element in root.findall(f".//{_W}{revision_tag}")
        if element.find(f".//{_W}{text_tag}") is not None
    ]


class _StaticContextProvider(ReviewContextProvider):
    def context_for(
        self,
        *,
        profile: ReviewProfile,
        document: ReviewDocument,
        state: ReviewState,
        scope,
        node,
    ) -> ReviewContext:
        return ReviewContext(
            scope=scope,
            node_id=node.id,
            data={"grounding": "Dike-style grounding", "source": "test"},
        )

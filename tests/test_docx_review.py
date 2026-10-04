"""One DOCX is the review: stay-or-go on that same file."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument

from reviewkit import (
    AddComment,
    ChangeText,
    DeleteComment,
    Jednostka,
    Poziom,
    ReviewDecision,
    Ruch,
    UpdateComment,
    read_comments,
    review_one_docx,
)
from reviewkit.stay_or_go import stay_or_go

_FIRST = "Pierwsze zdanie."
_SECOND = "Drugie zdanie."
_PARAGRAPH_TWO = "Drugi akapit."
_THIRD = "Trzecie zdanie."
_NOTE_ONE = "uwaga pierwsza"
_NOTE_TWO = "uwaga druga"
_NOTE_ONE_UPDATED = "uwaga pierwsza poprawiona"
_CHANGED = "Pierwsze zdanie poprawione."


def _source_docx(path: Path) -> Path:
    docx = DocxDocument()
    docx.add_heading("Rozdział 1", level=1)
    docx.add_paragraph(f"{_FIRST} {_SECOND}")
    docx.add_paragraph(_PARAGRAPH_TWO)
    docx.add_heading("Rozdział 2", level=1)
    docx.add_paragraph(_THIRD)
    docx.save(path)
    return path


class SameFileReviewer:
    """Stay on the first zdanie for two comments, then later levels mutate the file."""

    def __init__(self) -> None:
        self.zdanie_ids: list[str] = []
        self.poziomy: list[Poziom] = []

    def consider(self, unit: Jednostka) -> ReviewDecision:
        self.poziomy.append(unit.poziom)
        if unit.poziom is Poziom.ZDANIE:
            return self._zdanie(unit)
        if unit.poziom is Poziom.AKAPIT:
            return self._akapit(unit)
        if unit.poziom is Poziom.ROZDZIAL:
            return self._rozdzial(unit)
        return self._calosc(unit)

    def _zdanie(self, unit: Jednostka) -> ReviewDecision:
        if unit.visit == 1:
            self.zdanie_ids.append(unit.node_id)
        if len(self.zdanie_ids) == 1 and unit.node_id == self.zdanie_ids[0]:
            if unit.visit == 1:
                return ReviewDecision(Ruch.STAY, (AddComment(_NOTE_ONE),))
            if unit.visit == 2:
                assert len(read_comments(unit.path)) == 1
                return ReviewDecision(Ruch.GO, (AddComment(_NOTE_TWO),))
        if len(self.zdanie_ids) == 2:
            comments = read_comments(unit.path)
            assert [comment.text for comment in comments] == [_NOTE_ONE, _NOTE_TWO]
        return ReviewDecision(Ruch.GO)

    def _akapit(self, unit: Jednostka) -> ReviewDecision:
        if unit.visit == 1 and unit.node_id == "p1":
            comment = next(item for item in read_comments(unit.path) if item.text == _NOTE_ONE)
            return ReviewDecision(Ruch.GO, (UpdateComment(comment.id, _NOTE_ONE_UPDATED),))
        return ReviewDecision(Ruch.GO)

    def _rozdzial(self, unit: Jednostka) -> ReviewDecision:
        if unit.visit == 1 and unit.node_id == "s1":
            comment = next(item for item in read_comments(unit.path) if item.text == _NOTE_TWO)
            return ReviewDecision(Ruch.GO, (DeleteComment(comment.id),))
        return ReviewDecision(Ruch.GO)

    def _calosc(self, unit: Jednostka) -> ReviewDecision:
        if unit.document_pass == 1 and unit.visit == 1:
            return ReviewDecision(Ruch.GO, (ChangeText(_FIRST, _CHANGED),))
        return ReviewDecision(Ruch.GO)


def test_one_docx_walk_lands_on_the_same_file(tmp_path: Path) -> None:
    path = _source_docx(tmp_path / "reviewed.docx")
    reviewer = SameFileReviewer()

    result = review_one_docx(path, reviewer, document_passes=2)

    assert result.reviewed_docx == path
    walk = result.metrics["walk"]
    poziomy = [event["poziom"] for event in walk]
    assert "grain" not in poziomy
    assert "percent" not in poziomy
    assert "sides" not in poziomy
    assert set(poziomy) == {"zdanie", "akapit", "rozdział", "całość"}
    assert poziomy == sorted(poziomy, key=["zdanie", "akapit", "rozdział", "całość"].index)

    zdanie_events = [event for event in walk if event["poziom"] == "zdanie"]
    first_id = zdanie_events[0]["node_id"]
    first_sentence = [event for event in zdanie_events if event["node_id"] == first_id]
    assert first_sentence[0]["ruch"] == "stay"
    assert first_sentence[0]["effects"] == ["add_comment"]
    assert first_sentence[0]["comment_texts"] == [_NOTE_ONE]
    assert first_sentence[1]["ruch"] == "go"
    assert first_sentence[1]["effects"] == ["add_comment"]
    assert first_sentence[1]["comment_texts"] == [_NOTE_ONE, _NOTE_TWO]
    later_zdanie = [event for event in zdanie_events if event["node_id"] != first_id]
    assert later_zdanie
    assert later_zdanie[0]["comment_texts"] == [_NOTE_ONE, _NOTE_TWO]

    assert any(
        event["poziom"] == "akapit" and "update_comment" in event["effects"] for event in walk
    )
    assert any(
        event["poziom"] == "rozdział" and "delete_comment" in event["effects"] for event in walk
    )
    calosc = [event for event in walk if event["poziom"] == "całość"]
    assert {event["document_pass"] for event in calosc} == {1, 2}
    changed = next(event for event in calosc if "change_text" in event["effects"])
    assert _CHANGED in changed["file_text"]
    assert changed["document_pass"] == 1
    assert any(event["document_pass"] == 2 for event in calosc)

    comments = read_comments(path)
    assert [comment.text for comment in comments] == [_NOTE_ONE_UPDATED]
    assert result.document is not None
    assert _CHANGED in result.document.text
    assert _SECOND in result.document.text


def test_readme_names_the_walk_and_same_file() -> None:
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")
    for token in ("zdanie", "akapit", "rozdział", "całość", "stay or go", "```mermaid"):
        assert token in readme
    assert "grain" not in readme.split("## Pack", 1)[0]
    assert "review_one_docx" in readme
    assert "same file" in readme
    assert "abstract copy" in readme


def test_stay_or_go_iterates_until_go() -> None:
    visits: list[int] = []

    def consider(visit: int) -> str:
        visits.append(visit)
        return "go" if visit == 2 else "stay"

    assert list(stay_or_go(consider, is_go=lambda ruch: ruch == "go")) == ["stay", "go"]
    assert visits == [1, 2]

"""One DOCX is reviewed by walking that same file."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument

from reviewkit import (
    AKAPIT,
    CALOSC,
    ROZDZIAL,
    ZDANIE,
    StayOrGo,
    load_docx,
    read_comments,
    review_docx,
)
from reviewkit.live_docx import LiveDocx
from reviewkit.walk import ReviewUnit

_FIRST = "First sentence."
_SECOND = "Second sentence."
_THIRD = "Third sentence lives here."
_THIRD_EDITED = "Third sentence was edited."
_NOTE_ONE = "first note on the opening sentence"
_NOTE_TWO = "second note on the same sentence"
_NOTE_UPDATED = "updated note on the opening sentence"


def _sample_docx(path: Path) -> Path:
    document = DocxDocument()
    document.add_heading("Rozdział 1", level=1)
    document.add_paragraph(f"{_FIRST} {_SECOND}")
    document.add_paragraph(_THIRD)
    document.save(path)
    return path


class ScriptedReviewer:
    def __init__(self) -> None:
        self.comments_before_second_sentence: list[str] | None = None
        self.second_sentence_seen = False
        self.updated_id: str | None = None
        self.deleted_id: str | None = None
        self.saw_update_on_file = False
        self.saw_delete_on_file = False
        self.saw_text_change_on_file = False
        self.comment_ids: list[str] = []

    def decide(self, unit: ReviewUnit, docx: LiveDocx) -> StayOrGo:
        if unit.level == ZDANIE and unit.text == _FIRST and unit.stay_index == 0:
            assert self.second_sentence_seen is False
            self.comment_ids.append(_comment_on_unit(docx, unit, _NOTE_ONE))
            return StayOrGo.STAY
        if unit.level == ZDANIE and unit.text == _FIRST and unit.stay_index == 1:
            assert self.second_sentence_seen is False
            self.comment_ids.append(_comment_on_unit(docx, unit, _NOTE_TWO))
            sitting = {comment.text for comment in read_comments(docx.path)}
            assert sitting >= {_NOTE_ONE, _NOTE_TWO}
            self.comments_before_second_sentence = [
                comment.text for comment in read_comments(docx.path)
            ]
            return StayOrGo.GO
        if unit.level == ZDANIE and unit.text == _SECOND:
            self.second_sentence_seen = True
            assert self.comments_before_second_sentence is not None
            return StayOrGo.GO
        if unit.level == AKAPIT and not self.saw_update_on_file:
            self.updated_id = docx.update_comment(self.comment_ids[0], _NOTE_UPDATED)
            texts = [comment.text for comment in read_comments(docx.path)]
            assert _NOTE_UPDATED in texts
            assert _NOTE_ONE not in texts
            self.saw_update_on_file = True
            return StayOrGo.GO
        if unit.level == ROZDZIAL and not self.saw_delete_on_file:
            remaining = next(
                comment.id for comment in read_comments(docx.path) if comment.text == _NOTE_TWO
            )
            self.deleted_id = remaining
            docx.delete_comment(remaining)
            texts = [comment.text for comment in read_comments(docx.path)]
            assert _NOTE_TWO not in texts
            self.saw_delete_on_file = True
            return StayOrGo.GO
        if unit.level == CALOSC and unit.calosc_pass == 0 and not self.saw_text_change_on_file:
            paragraph = next(node for node in docx.load().iter_paragraphs() if _THIRD in node.text)
            assert paragraph.locator is not None
            start = paragraph.text.find(_THIRD)
            docx.change_text(
                locator=paragraph.locator,
                start=start,
                end=start + len(_THIRD),
                replacement=_THIRD_EDITED,
            )
            assert _THIRD_EDITED in docx.load().text
            self.saw_text_change_on_file = True
            return StayOrGo.GO
        return StayOrGo.GO


def _comment_on_unit(docx: LiveDocx, unit: ReviewUnit, text: str) -> str:
    assert unit.paragraph_locator is not None
    assert unit.char_start is not None
    assert unit.char_end is not None
    return docx.add_comment(
        locator=unit.paragraph_locator,
        start=unit.char_start,
        end=unit.char_end,
        text=text,
        expected_text=unit.text,
    )


def test_review_walks_one_docx_in_place(tmp_path: Path) -> None:
    path = _sample_docx(tmp_path / "source.docx")
    reviewer = ScriptedReviewer()

    result = review_docx(path, reviewer, calosc_times=2)

    assert result.path == path
    levels = [visit.level for visit in result.visits]
    assert levels[0] == ZDANIE
    assert ROZDZIAL not in levels[: levels.index(AKAPIT)]
    assert CALOSC not in levels[: levels.index(ROZDZIAL)]
    zdanie = [visit for visit in result.visits if visit.level == ZDANIE]
    assert all(visit.level == ZDANIE for visit in result.visits[: len(zdanie)])
    assert [visit.stay_index for visit in zdanie[:2]] == [0, 1]
    assert zdanie[0].text == _FIRST
    assert zdanie[1].text == _FIRST
    assert zdanie[2].text == _SECOND
    assert reviewer.second_sentence_seen is True
    assert reviewer.comments_before_second_sentence is not None
    assert reviewer.comments_before_second_sentence.count(_NOTE_ONE) == 1
    assert reviewer.comments_before_second_sentence.count(_NOTE_TWO) == 1

    akapit_at = levels.index(AKAPIT)
    rozdzial_at = levels.index(ROZDZIAL)
    calosc_at = levels.index(CALOSC)
    assert akapit_at < rozdzial_at < calosc_at
    assert levels.count(AKAPIT) >= 2
    assert ROZDZIAL in levels
    calosc = [visit for visit in result.visits if visit.level == CALOSC]
    assert [visit.calosc_pass for visit in calosc] == [0, 1]

    assert reviewer.saw_update_on_file
    assert reviewer.saw_delete_on_file
    assert reviewer.saw_text_change_on_file
    texts = [comment.text for comment in read_comments(path)]
    assert _NOTE_UPDATED in texts
    assert _NOTE_TWO not in texts
    assert _NOTE_ONE not in texts
    document = load_docx(path)
    assert _THIRD_EDITED in document.text
    assert document.source_path == path


def test_readme_describes_the_same_file_stay_or_go_walk() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "```mermaid" in readme
    assert readme.count("```mermaid") == 1
    mermaid = readme.split("```mermaid", 1)[1].split("```", 1)[0]
    for name in ("zdanie", "akapit", "rozdział", "całość"):
        assert name in mermaid
    assert "zdanie 1" in mermaid
    assert "zdanie 2" in mermaid
    assert "akapit 1" in mermaid
    assert "akapit 2" in mermaid
    assert "rozdział 1" in mermaid
    assert "rozdział 2" in mermaid
    assert "stay or go" in mermaid
    assert mermaid.count("stay or go") >= 4
    assert "zNext --> zLoop" not in mermaid
    assert "comment or text on this DOCX" in mermaid
    assert "walk całość again, n times" in mermaid
    assert "same DOCX" in mermaid
    walk = readme.split("## The walk")[1].split("##")[0]
    assert "grain" not in walk
    assert "percent" not in walk
    assert "sides" not in walk

"""Same-file DOCX walk: zdanie, then akapit, then rozdział, then całość n times."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument
from docxtor import CommentAuthor, CommentRange, add_comment

from reviewkit import (
    Effect,
    EffectKind,
    Poziom,
    StayOrGo,
    Visit,
    VisitDecision,
    load_docx,
    read_comments,
    review_docx,
)
from reviewkit.models import ReviewBoundError
from reviewkit.stay import stay_loop


def _write_source(path: Path) -> Path:
    docx = DocxDocument()
    docx.add_heading("Rozdział 1", level=1)
    docx.add_paragraph("First sentence. Second sentence.")
    docx.add_paragraph("Third sentence.")
    docx.save(path)
    third = "Third sentence."
    path.write_bytes(
        add_comment(
            path.read_bytes(),
            CommentRange("body:p:2", 0, len(third), third),
            "stary",
            CommentAuthor(author="Source", initials="SO"),
        ).data
    )
    return path


class _WalkReviewer:
    """Stay on the first zdanie twice; update then delete the source comment."""

    def __init__(self) -> None:
        self.visits: list[Visit] = []
        self.comments_on_disk: list[list[str]] = []
        self.paths: list[Path] = []
        self.first_zdanie_key: str | None = None
        self.stary_id: str | None = None

    def visit(self, visit: Visit) -> VisitDecision:
        self.visits.append(visit)
        self.paths.append(visit.path)
        self.comments_on_disk.append([comment.text for comment in read_comments(visit.path)])
        unit = visit.unit
        if unit.poziom is Poziom.ZDANIE:
            if self.first_zdanie_key is None:
                self.first_zdanie_key = unit.key
            if unit.key == self.first_zdanie_key:
                if visit.visit_index == 0:
                    return VisitDecision(
                        StayOrGo.STAY,
                        (Effect(kind=EffectKind.ADD_COMMENT, comment="pierwsza"),),
                    )
                return VisitDecision(
                    StayOrGo.GO,
                    (Effect(kind=EffectKind.ADD_COMMENT, comment="druga"),),
                )
            existing = [comment for comment in unit.comments if comment.text == "stary"]
            if existing:
                self.stary_id = existing[0].id
                return VisitDecision(
                    StayOrGo.GO,
                    (
                        Effect(
                            kind=EffectKind.UPDATE_COMMENT,
                            comment_id=existing[0].id,
                            comment="zaktualizowany",
                        ),
                    ),
                )
            return VisitDecision(StayOrGo.GO)
        if unit.poziom is Poziom.AKAPIT and self.stary_id:
            if any(comment.id == self.stary_id for comment in unit.comments):
                return VisitDecision(
                    StayOrGo.GO,
                    (Effect(kind=EffectKind.DELETE_COMMENT, comment_id=self.stary_id),),
                )
            return VisitDecision(StayOrGo.GO)
        if unit.poziom is Poziom.CALOSC and visit.visit_index == 0:
            return VisitDecision(
                StayOrGo.STAY,
                (
                    Effect(
                        kind=EffectKind.CHANGE_TEXT,
                        original_text="Third sentence.",
                        replacement_text="Third clause.",
                    ),
                ),
            )
        return VisitDecision(StayOrGo.GO)


def test_stay_loop_repeats_until_go() -> None:
    seen: list[int] = []

    def step(visit_index: int) -> StayOrGo:
        seen.append(visit_index)
        return StayOrGo.STAY if visit_index == 0 else StayOrGo.GO

    assert stay_loop(step, max_stays=4, node_id="p1.s1") == 2
    assert seen == [0, 1]


def test_stay_loop_fails_closed_when_stay_never_ends() -> None:
    try:
        stay_loop(lambda _index: StayOrGo.STAY, max_stays=2, node_id="p1.s1")
    except ReviewBoundError as exc:
        assert exc.node_id == "p1.s1"
        return
    raise AssertionError("expected ReviewBoundError")


def test_docx_walk_stays_on_first_zdanie_and_mutates_the_same_file(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source.docx")
    reviewer = _WalkReviewer()

    result = review_docx(source, reviewer)

    assert result.reviewed_docx == source
    assert result.artifacts["reviewed_docx"] == str(source)
    assert set(reviewer.paths) == {source}

    poziomy = [visit.unit.poziom for visit in reviewer.visits]
    last_zdanie = max(index for index, poziom in enumerate(poziomy) if poziom is Poziom.ZDANIE)
    first_akapit = next(index for index, poziom in enumerate(poziomy) if poziom is Poziom.AKAPIT)
    last_akapit = max(index for index, poziom in enumerate(poziomy) if poziom is Poziom.AKAPIT)
    first_rozdzial = next(
        index for index, poziom in enumerate(poziomy) if poziom is Poziom.ROZDZIAL
    )
    last_rozdzial = max(index for index, poziom in enumerate(poziomy) if poziom is Poziom.ROZDZIAL)
    first_calosc = next(index for index, poziom in enumerate(poziomy) if poziom is Poziom.CALOSC)
    assert last_zdanie < first_akapit
    assert last_akapit < first_rozdzial
    assert last_rozdzial < first_calosc

    zdania = [visit for visit in reviewer.visits if visit.unit.poziom is Poziom.ZDANIE]
    assert zdania[0].visit_index == 0
    assert zdania[1].unit.key == zdania[0].unit.key
    assert zdania[1].visit_index == 1
    assert zdania[2].unit.key != zdania[0].unit.key
    assert "pierwsza" not in reviewer.comments_on_disk[0]
    assert "pierwsza" in reviewer.comments_on_disk[1]
    assert "druga" not in reviewer.comments_on_disk[1]
    assert reviewer.comments_on_disk[1].count("pierwsza") == 1

    akapity = [visit for visit in reviewer.visits if visit.unit.poziom is Poziom.AKAPIT]
    assert len(akapity) == 2
    rozdzialy = [visit for visit in reviewer.visits if visit.unit.poziom is Poziom.ROZDZIAL]
    assert len(rozdzialy) == 1
    calosci = [visit for visit in reviewer.visits if visit.unit.poziom is Poziom.CALOSC]
    assert len(calosci) == 2
    assert calosci[0].visit_index == 0
    assert calosci[1].visit_index == 1

    live_comments = read_comments(source)
    texts = [comment.text for comment in live_comments]
    assert texts.count("pierwsza") == 1
    assert texts.count("druga") == 1
    assert "stary" not in texts
    assert "zaktualizowany" not in texts
    first_sentence_comments = [
        comment
        for comment in live_comments
        if comment.anchor_text == "First sentence."
        or (comment.start_offset == 0 and comment.end_offset == len("First sentence."))
    ]
    assert {comment.text for comment in first_sentence_comments} >= {"pierwsza", "druga"}

    live = load_docx(source)
    paragraphs = {paragraph.locator: paragraph.text for paragraph in live.iter_paragraphs()}
    assert paragraphs["body:p:1"] == "First sentence. Second sentence."
    assert paragraphs["body:p:2"] == "Third clause."

    other = tmp_path / "reviewed.docx"
    assert not other.exists()

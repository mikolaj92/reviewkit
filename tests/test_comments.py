"""Existing Word comments are walk input."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument

from reviewkit.comments import DocxComment, comments_for_locator, read_comments
from reviewkit.parser_docx import load_docx

_CLAUSE = "Umowa zostaje zawarta na czas nieokreślony. Okres wypowiedzenia wynosi 3 miesiące."
_LAWYER_NOTE = "sprawdzić czy to jest w umowie"


def _clause_docx(
    path: Path,
    *,
    clause: str = _CLAUSE,
    note: str = _LAWYER_NOTE,
    author: str = "Prawnik",
    initials: str = "PR",
) -> Path:
    docx = DocxDocument()
    paragraph = docx.add_paragraph(clause)
    docx.add_comment(runs=paragraph.runs[0], text=note, author=author, initials=initials)
    docx.add_paragraph("Wynagrodzenie wynosi 10000 PLN.")
    docx.save(path)
    return path


def test_read_comments_exposes_anchor_text_author_and_locator(tmp_path: Path) -> None:
    path = _clause_docx(tmp_path / "clause.docx")

    comments = read_comments(path)

    assert len(comments) == 1
    comment = comments[0]
    assert comment.text == _LAWYER_NOTE
    assert comment.author == "Prawnik"
    assert comment.initials == "PR"
    assert comment.locator == "body:p:0"
    assert comment.anchor_text == _CLAUSE
    assert comment.start_offset == 0
    assert comment.end_offset == len(_CLAUSE)
    assert "w:comment" not in comment.text


def test_load_docx_attaches_comment_to_the_clause_paragraph(tmp_path: Path) -> None:
    path = _clause_docx(tmp_path / "clause.docx")

    document = load_docx(path)
    clause = document.sections[0].paragraphs[0]
    other = document.sections[0].paragraphs[1]

    assert document.comments
    assert document.comments[0].text == _LAWYER_NOTE
    assert clause.text == _CLAUSE
    assert [comment.text for comment in clause.comments] == [_LAWYER_NOTE]
    assert clause.comments[0].anchor_text == _CLAUSE
    assert other.comments == []
    assert comments_for_locator(document.comments, clause.locator) == clause.comments


def test_read_comments_table_cell_gets_table_locator(tmp_path: Path) -> None:
    path = tmp_path / "table.docx"
    docx = DocxDocument()
    table = docx.add_table(rows=1, cols=1)
    cell_paragraph = table.cell(0, 0).paragraphs[0]
    cell_paragraph.add_run("Treść w tabeli.")
    docx.add_comment(runs=cell_paragraph.runs[0], text="Uwaga do komórki.", author="Prawnik")
    docx.save(path)

    comments = read_comments(path)
    assert len(comments) == 1
    assert comments[0].locator == "table:0:r:0:c:0:p:0"
    assert comments[0].anchor_text == "Treść w tabeli."


def test_read_comments_exposes_unique_sentence_range(tmp_path: Path) -> None:
    from docxtor import CommentAuthor, CommentRange, add_comment

    first = "Strony mogą wypowiedzieć umowę."
    second = "Umowa obowiązuje od dnia podpisania."
    paragraph = f"{first} {second}"
    path = tmp_path / "sentence.docx"
    docx = DocxDocument()
    docx.add_paragraph(paragraph)
    docx.save(path)
    path.write_bytes(
        add_comment(
            path.read_bytes(),
            CommentRange(
                locator="body:p:0",
                start_offset=0,
                end_offset=len(first),
                expected_text=first,
            ),
            "termin",
            CommentAuthor(author="Reviewer", initials="RV"),
        ).data
    )

    comments = read_comments(path)
    assert len(comments) == 1
    comment = comments[0]
    assert comment.anchor_text == first
    assert comment.start_offset == 0
    assert comment.end_offset == len(first)
    assert comment.end_offset < len(paragraph)


def test_comments_for_locator_filters() -> None:
    comments = [
        DocxComment(
            id="0", author="A", initials="A", text="one", locator="body:p:0", anchor_text="x"
        ),
        DocxComment(
            id="1", author="B", initials="B", text="two", locator="body:p:1", anchor_text="y"
        ),
    ]
    assert [comment.id for comment in comments_for_locator(comments, "body:p:1")] == ["1"]
    assert comments_for_locator(comments, None) == []

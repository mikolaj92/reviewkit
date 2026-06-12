from pathlib import Path

from docx import Document as DocxDocument

from reviewkit.parser_docx import load_docx


def test_document_is_split_into_sections_paragraphs_and_sentences(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_heading("Rozdział 1", level=1)
    docx.add_paragraph("Ala ma kota. Kot ma dom.")
    docx.save(input_path)

    document = load_docx(input_path)

    assert len(document.sections) == 1
    assert document.sections[0].id == "s1"
    assert document.sections[0].title == "Rozdział 1"
    assert len(document.sections[0].paragraphs) == 1
    paragraph = document.sections[0].paragraphs[0]
    assert paragraph.id == "p1"
    assert paragraph.locator == "body:p:1"
    assert document.metadata["tracked_revisions_detected"] == "false"
    assert [sentence.text for sentence in paragraph.sentences] == ["Ala ma kota.", "Kot ma dom."]


def test_docx_parser_reads_table_paragraphs_with_locators(tmp_path: Path) -> None:
    input_path = tmp_path / "table.docx"
    docx = DocxDocument()
    table = docx.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Treść w tabeli."
    docx.save(input_path)

    document = load_docx(input_path)

    paragraph = document.sections[0].paragraphs[0]
    assert paragraph.text == "Treść w tabeli."
    assert paragraph.locator == "table:0:row:0:cell:0:p:0"

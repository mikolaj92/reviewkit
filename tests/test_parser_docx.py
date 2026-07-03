from pathlib import Path

from docx import Document as DocxDocument

from reviewkit.parser_docx import load_docx, split_sentences


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


def test_decimal_numbers_do_not_split_a_sentence() -> None:
    assert split_sentences("Pi is 3.14 today.") == ["Pi is 3.14 today."]


def test_abbreviations_do_not_over_split() -> None:
    assert split_sentences("Sp. z o.o.") == ["Sp. z o.o."]
    assert split_sentences("See J. R. R. Tolkien.") == ["See J. R. R. Tolkien."]


def test_genuine_sentence_boundaries_still_split() -> None:
    assert split_sentences("First one. Second one!") == ["First one.", "Second one!"]


def test_english_styled_heading_starts_a_new_section(tmp_path: Path) -> None:
    input_path = tmp_path / "headings.docx"
    docx = DocxDocument()
    docx.add_heading("Introduction", level=1)
    docx.add_paragraph("First body paragraph.")
    docx.add_heading("Conclusion", level=2)
    docx.add_paragraph("Second body paragraph.")
    docx.save(input_path)

    document = load_docx(input_path)

    assert [section.title for section in document.sections] == ["Introduction", "Conclusion"]
    assert [len(section.paragraphs) for section in document.sections] == [1, 1]


def test_core_source_contains_no_polish_or_domain_vocabulary() -> None:
    src_root = Path(__file__).resolve().parent.parent / "src" / "reviewkit"
    forbidden = [
        "naglowek",
        "nagłówek",
        "niski",
        "średni",
        "sredni",
        "wysoki",
        "opowiadanie",
        "nauczyciel",
        "uczeń",
        "ucznia",
        "literówk",
    ]
    offenders: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(src_root)}: {token!r}")
    assert not offenders, "domain/language vocabulary must not appear in core src: " + ", ".join(
        offenders
    )


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


def test_merged_table_cells_are_walked_exactly_once(tmp_path: Path) -> None:
    # row.cells yields a merged cell once per grid position it spans, so without dedup a
    # merged cell's paragraphs are emitted multiple times: reviewed twice, edited twice.
    input_path = tmp_path / "merged.docx"
    docx = DocxDocument()
    table = docx.add_table(rows=2, cols=3)
    for row in range(2):
        for col in range(3):
            table.cell(row, col).paragraphs[0].add_run(f"r{row}c{col}")
    table.cell(0, 0).merge(table.cell(0, 1))  # horizontal merge
    table.cell(0, 2).merge(table.cell(1, 2))  # vertical merge
    docx.save(input_path)

    document = load_docx(input_path)
    table_paragraphs = [
        paragraph
        for paragraph in document.iter_paragraphs()
        if (paragraph.locator or "").startswith("table:")
    ]

    # 4 physical cells survive the two merges; each merged cell keeps both its paragraphs
    # but is walked once, so 6 nodes total with no text (and no locator) emitted twice.
    assert len(table_paragraphs) == 6
    texts = [paragraph.text for paragraph in table_paragraphs]
    assert len(texts) == len(set(texts))
    locators = [paragraph.locator for paragraph in table_paragraphs]
    assert len(locators) == len(set(locators))

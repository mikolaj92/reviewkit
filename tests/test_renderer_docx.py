from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document as DocxDocument

from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewLocator,
    ReviewScope,
)
from reviewkit.parser_docx import load_docx
from reviewkit.renderer_docx import render_corrected_docx, render_reviewed_docx

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def test_reviewed_docx_patches_original_and_preserves_run_formatting(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    paragraph = docx.add_paragraph()
    paragraph.add_run("Plain ")
    target = paragraph.add_run("target")
    target.bold = True
    paragraph.add_run(" text")
    docx.save(input_path)

    document = load_docx(input_path)
    reviewed_path = render_reviewed_docx(
        document,
        [
            ReviewAction(
                scope=ReviewScope.PARAGRAPH,
                action_type=ReviewActionType.REPLACE,
                node_id="p1",
                original_text="target",
                replacement_text="replacement",
                reason="Use clearer wording.",
                status=ActionStatus.NOT_APPLIED,
            )
        ],
        tmp_path / "reviewed.docx",
    )

    document_xml = _part_xml(reviewed_path, "word/document.xml")
    root = ElementTree.fromstring(document_xml)
    paragraph_xml = root.find(f".//{_W}p")
    assert paragraph_xml is not None
    assert [child.tag for child in paragraph_xml] == [
        f"{_W}r",
        f"{_W}commentRangeStart",
        f"{_W}del",
        f"{_W}ins",
        f"{_W}commentRangeEnd",
        f"{_W}r",
        f"{_W}r",
    ]
    assert _revision_texts(document_xml, "del", "delText") == ["target"]
    assert _revision_texts(document_xml, "ins", "t") == ["replacement"]
    assert root.find(f".//{_W}del/{_W}r/{_W}rPr/{_W}b") is not None
    assert "[DELETE:" not in document_xml


def test_reviewed_docx_patches_table_header_and_footer_paragraphs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Body text.")
    table = docx.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Table bład."
    section = docx.sections[0]
    section.header.paragraphs[0].text = "Header bład."
    section.footer.paragraphs[0].text = "Footer bład."
    docx.save(input_path)

    document = load_docx(input_path)
    actions = [
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.REPLACE,
            node_id=paragraph.id,
            original_text="bład",
            replacement_text="błąd",
            reason="Fix typo.",
            status=ActionStatus.APPLIED,
        )
        for paragraph in document.iter_paragraphs()
        if "bład" in paragraph.text
    ]

    reviewed_path = render_reviewed_docx(document, actions, tmp_path / "reviewed.docx")

    document_xml = _part_xml(reviewed_path, "word/document.xml")
    header_xml = _part_xml(reviewed_path, "word/header1.xml")
    footer_xml = _part_xml(reviewed_path, "word/footer1.xml")
    assert _revision_texts(document_xml, "del", "delText") == ["bład"]
    assert _revision_texts(document_xml, "ins", "t") == ["błąd"]
    assert _revision_texts(header_xml, "del", "delText") == ["bład"]
    assert _revision_texts(header_xml, "ins", "t") == ["błąd"]
    assert _revision_texts(footer_xml, "del", "delText") == ["bład"]
    assert _revision_texts(footer_xml, "ins", "t") == ["błąd"]


def test_reviewed_docx_stamps_caller_supplied_reviewer_identity(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Plain target text")
    docx.save(input_path)

    document = load_docx(input_path)
    reviewed_path = render_reviewed_docx(
        document,
        [
            ReviewAction(
                scope=ReviewScope.PARAGRAPH,
                action_type=ReviewActionType.REPLACE,
                node_id="p1",
                original_text="target",
                replacement_text="replacement",
                reason="Use clearer wording.",
                status=ActionStatus.NOT_APPLIED,
            )
        ],
        tmp_path / "reviewed.docx",
        comment_author="External Reviewer",
        comment_initials="ER",
    )

    document_xml = _part_xml(reviewed_path, "word/document.xml")
    revision = ElementTree.fromstring(document_xml).find(f".//{_W}ins")
    assert revision is not None
    assert revision.get(f"{_W}author") == "External Reviewer"

    comments_xml = _part_xml(reviewed_path, "word/comments.xml")
    comment = ElementTree.fromstring(comments_xml).find(f".//{_W}comment")
    assert comment is not None
    assert comment.get(f"{_W}author") == "External Reviewer"
    assert comment.get(f"{_W}initials") == "ER"


def test_reviewed_docx_uses_neutral_default_reviewer_identity(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Plain target text")
    docx.save(input_path)

    document = load_docx(input_path)
    reviewed_path = render_reviewed_docx(
        document,
        [
            ReviewAction(
                scope=ReviewScope.PARAGRAPH,
                action_type=ReviewActionType.REPLACE,
                node_id="p1",
                original_text="target",
                replacement_text="replacement",
                reason="Use clearer wording.",
                status=ActionStatus.NOT_APPLIED,
            )
        ],
        tmp_path / "reviewed.docx",
    )

    document_xml = _part_xml(reviewed_path, "word/document.xml")
    revision = ElementTree.fromstring(document_xml).find(f".//{_W}ins")
    assert revision is not None
    assert revision.get(f"{_W}author") == "Reviewer"

    comments_xml = _part_xml(reviewed_path, "word/comments.xml")
    comment = ElementTree.fromstring(comments_xml).find(f".//{_W}comment")
    assert comment is not None
    assert comment.get(f"{_W}author") == "Reviewer"
    assert comment.get(f"{_W}initials") == "RV"


def test_reviewed_docx_revision_dates_are_deterministic_by_default(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Plain target text")
    docx.save(input_path)

    document = load_docx(input_path)
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE,
        node_id="p1",
        original_text="target",
        replacement_text="replacement",
        reason="Use clearer wording.",
        status=ActionStatus.NOT_APPLIED,
    )

    first = render_reviewed_docx(document, [action], tmp_path / "first.docx")
    second = render_reviewed_docx(document, [action], tmp_path / "second.docx")

    first_date = ElementTree.fromstring(_part_xml(first, "word/document.xml")).find(f".//{_W}ins")
    second_date = ElementTree.fromstring(_part_xml(second, "word/document.xml")).find(f".//{_W}ins")
    assert first_date is not None and second_date is not None
    assert first_date.get(f"{_W}date") == second_date.get(f"{_W}date")
    assert first_date.get(f"{_W}date") == "1970-01-01T00:00:00+00:00"


def test_reviewed_docx_accepts_an_explicit_revision_timestamp(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Plain target text")
    docx.save(input_path)

    document = load_docx(input_path)
    stamp = datetime(2026, 7, 3, 9, 30, tzinfo=UTC)
    reviewed_path = render_reviewed_docx(
        document,
        [
            ReviewAction(
                scope=ReviewScope.PARAGRAPH,
                action_type=ReviewActionType.REPLACE,
                node_id="p1",
                original_text="target",
                replacement_text="replacement",
                reason="Use clearer wording.",
                status=ActionStatus.NOT_APPLIED,
            )
        ],
        tmp_path / "reviewed.docx",
        revision_timestamp=stamp,
    )

    revision = ElementTree.fromstring(_part_xml(reviewed_path, "word/document.xml")).find(
        f".//{_W}ins"
    )
    assert revision is not None
    assert revision.get(f"{_W}date") == "2026-07-03T09:30:00+00:00"


def test_corrected_docx_preserves_original_structure_and_formatting(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_heading("Rozdział pierwszy", level=1)
    paragraph = docx.add_paragraph()
    paragraph.add_run("Ala ma ")
    kept = paragraph.add_run("kota")
    kept.bold = True
    paragraph.add_run(" oraz bład.")
    table = docx.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Tabela bład."
    docx.save(input_path)

    document = load_docx(input_path)
    actions = [
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.REPLACE,
            node_id=paragraph_node.id,
            original_text="bład",
            replacement_text="błąd",
            reason="Fix typo.",
            status=ActionStatus.APPLIED,
        )
        for paragraph_node in document.iter_paragraphs()
        if "bład" in paragraph_node.text
    ]

    corrected_path = render_corrected_docx(document, actions, tmp_path / "corrected.docx")

    corrected = DocxDocument(corrected_path)
    # Structure preserved: the heading and the table survive the round-trip.
    assert any(p.style.name.startswith("Heading") for p in corrected.paragraphs)
    assert any("Rozdział pierwszy" == p.text for p in corrected.paragraphs)
    assert len(corrected.tables) == 1
    assert corrected.tables[0].cell(0, 0).text == "Tabela błąd."
    # Edit applied cleanly with no tracked-change markup.
    body_text = "\n".join(p.text for p in corrected.paragraphs)
    assert "Ala ma kota oraz błąd." in body_text
    document_xml = _part_xml(corrected_path, "word/document.xml")
    assert "<w:ins" not in document_xml
    assert "<w:del" not in document_xml
    # Run-level formatting on the untouched bold run is retained.
    root = ElementTree.fromstring(document_xml)
    assert root.find(f".//{_W}r/{_W}rPr/{_W}b") is not None


def test_locator_edit_aligns_offsets_past_leading_whitespace(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    paragraph = docx.add_paragraph()
    paragraph.add_run("   ")  # leading whitespace preserved in the source run
    paragraph.add_run("Hello world.")
    docx.save(input_path)

    document = load_docx(input_path)
    paragraph_node = document.sections[0].paragraphs[0]
    assert paragraph_node.text == "Hello world."
    # Offsets are relative to the stripped node text: "world" is [6, 11).
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE,
        node_id=paragraph_node.id,
        original_text="world",
        replacement_text="planet",
        locator=ReviewLocator(node_id=paragraph_node.id, char_start=6, char_end=11),
        reason="Clarify.",
        status=ActionStatus.APPLIED,
    )

    corrected_path = render_corrected_docx(document, [action], tmp_path / "corrected.docx")
    corrected = DocxDocument(corrected_path)
    corrected_text = corrected.paragraphs[0].text
    # The edit lands on "world" despite the 3-char leading whitespace offset skew.
    assert corrected_text.strip() == "Hello planet."


def test_edited_paragraph_preserves_images_hyperlinks_tabs_and_breaks(tmp_path: Path) -> None:
    from docx.oxml import OxmlElement

    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    paragraph = docx.add_paragraph()
    paragraph.add_run("Ala ma ")
    image_run = paragraph.add_run()  # inline image lives in its own run
    image_run._r.append(OxmlElement("w:drawing"))
    paragraph.add_run("kota")
    tab_run = paragraph.add_run()
    tab_run._r.append(OxmlElement("w:tab"))
    paragraph.add_run("oraz")
    break_run = paragraph.add_run()
    break_run._r.append(OxmlElement("w:br"))
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink_run = OxmlElement("w:r")
    hyperlink_text = OxmlElement("w:t")
    hyperlink_text.text = "link"
    hyperlink_run.append(hyperlink_text)
    hyperlink.append(hyperlink_run)
    paragraph._p.append(hyperlink)
    paragraph.add_run(" koniec")
    docx.save(input_path)

    document = load_docx(input_path)
    node = document.sections[0].paragraphs[0]
    assert node.text == "Ala ma kota\toraz\nlink koniec"
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE,
        node_id=node.id,
        original_text="kota",
        replacement_text="pies",
        reason="Change the animal.",
        status=ActionStatus.APPLIED,
    )

    # corrected.docx: the edit applies cleanly and every inline object survives.
    corrected_path = render_corrected_docx(document, [action], tmp_path / "corrected.docx")
    corrected_xml = _part_xml(corrected_path, "word/document.xml")
    assert "<w:drawing" in corrected_xml
    assert "<w:tab" in corrected_xml
    assert "<w:br" in corrected_xml
    assert "<w:hyperlink" in corrected_xml
    corrected_text = DocxDocument(corrected_path).paragraphs[0].text
    assert "pies" in corrected_text
    assert "kota" not in corrected_text
    assert "link" in corrected_text
    assert "<w:ins" not in corrected_xml and "<w:del" not in corrected_xml

    # reviewed.docx: tracked change is applied and every inline object survives.
    reviewed_path = render_reviewed_docx(document, [action], tmp_path / "reviewed.docx")
    reviewed_xml = _part_xml(reviewed_path, "word/document.xml")
    assert "<w:drawing" in reviewed_xml
    assert "<w:tab" in reviewed_xml
    assert "<w:br" in reviewed_xml
    assert "<w:hyperlink" in reviewed_xml
    assert _revision_texts(reviewed_xml, "del", "delText") == ["kota"]
    assert _revision_texts(reviewed_xml, "ins", "t") == ["pies"]


def _part_xml(path: Path, member: str) -> str:
    with ZipFile(path) as archive:
        return archive.read(member).decode()


def _revision_texts(xml: str, revision_tag: str, text_tag: str) -> list[str]:
    root = ElementTree.fromstring(xml)
    return [
        "".join(element.itertext())
        for element in root.findall(f".//{_W}{revision_tag}")
        if element.find(f".//{_W}{text_tag}") is not None
    ]

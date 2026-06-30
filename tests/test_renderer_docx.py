from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document as DocxDocument

from reviewkit.models import ActionStatus, ReviewAction, ReviewActionType, ReviewScope
from reviewkit.parser_docx import load_docx
from reviewkit.renderer_docx import render_reviewed_docx

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

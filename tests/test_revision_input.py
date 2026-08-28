from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document as DocxDocument
from lxml import etree

from reviewkit import DocxComment
from reviewkit.document import ReviewDocument
from reviewkit.models import RevisionCoverageError, RevisionCoverageState, RevisionLedger
from reviewkit.parser_docx import load_docx
from reviewkit.renderer_docx import render_corrected_docx, render_reviewed_docx

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def test_effective_projection_and_typed_ledger(tmp_path: Path) -> None:
    # Given: a Word document with one anchored source comment and both revision kinds.
    source = tmp_path / "revision-input.docx"
    document = DocxDocument()
    paragraph = document.add_paragraph()
    plain_run = paragraph.add_run("Plain ")
    document.add_comment(
        runs=plain_run,
        text="Source note.",
        author="Source reviewer",
        initials="SR",
    )
    document.save(source)
    _append_revisions(source)

    # When: ReviewKit reads the DOCX through its public parser contract.
    review_document = load_docx(source)

    # Then: the parser exposes the requested typed revision-aware public result.
    ledger = review_document.revision_ledger
    assert review_document.text == "Plain Inserted."
    assert [(entry.kind, entry.text, entry.locator) for entry in ledger.entries] == [
        ("inserted", "Inserted.", "body:p:0"),
        ("deleted", "Deleted.", "body:p:0"),
    ]
    assert ledger.entries[0].revision_id == "1"
    assert ledger.entries[0].author == "Source reviewer"
    assert review_document.comments == [
        DocxComment(
            id="0",
            author="Source reviewer",
            initials="SR",
            text="Source note.",
            locator="body:p:0",
            anchor_text="Plain ",
        )
    ]


def test_incomplete_revision_coverage_refuses_reviewed_output(tmp_path: Path) -> None:
    # Given: a parsed document whose source revision roles cannot be fully projected.
    document = ReviewDocument(
        revision_ledger=RevisionLedger(coverage=RevisionCoverageState.INCOMPLETE)
    )
    output = tmp_path / "reviewed.docx"

    # When / Then: publication fails before it creates an artifact.
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(document, [], output)
    assert not output.exists()


def test_incomplete_revision_coverage_refuses_corrected_output(tmp_path: Path) -> None:
    document = ReviewDocument(
        revision_ledger=RevisionLedger(coverage=RevisionCoverageState.INCOMPLETE)
    )
    output = tmp_path / "corrected.docx"
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_corrected_docx(document, [], output)
    assert not output.exists()


def test_unresolved_source_comment_refuses_reviewed_output(tmp_path: Path) -> None:
    # Given: a source comment body with no Word range anchor.
    source = tmp_path / "unresolved-comment.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.comments.add_comment(text="Unresolved note.", author="Source", initials="S")
    document.save(source)

    # When / Then: parsing marks coverage incomplete and blocks publication.
    review_document = load_docx(source)
    output = tmp_path / "reviewed.docx"
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], output)
    assert not output.exists()


def _append_revisions(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    paragraph.append(_revision("ins", "Inserted.", "1"))
    paragraph.append(_revision("del", "Deleted.", "2"))
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _revision(kind: str, text: str, revision_id: str) -> etree._Element:
    revision = etree.Element(f"{_W}{kind}")
    revision.set(f"{_W}id", revision_id)
    revision.set(f"{_W}author", "Source reviewer")
    run = etree.SubElement(revision, f"{_W}r")
    text_node = etree.SubElement(run, f"{_W}{'t' if kind == 'ins' else 'delText'}")
    text_node.text = text
    return revision

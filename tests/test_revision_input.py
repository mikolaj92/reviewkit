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


def test_supported_revision_coverage_ignores_empty_and_nested_wrappers(tmp_path: Path) -> None:
    # Given: supported revisions whose OOXML wrapper count is larger than their text spans.
    source = tmp_path / "wrapper-noise.docx"
    document = DocxDocument()
    document.add_paragraph("Plain ")
    document.save(source)
    _append_empty_nested_and_split_revisions(source)

    # When: ReviewKit projects effective text and the typed revision ledger.
    review_document = load_docx(source)

    # Then: direct revision-owned text is complete despite empty/nested wrappers and split spans.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.COMPLETE
    assert review_document.text == "Plain Inserted."
    assert [(entry.kind.value, entry.revision_id, entry.text) for entry in review_document.revision_ledger.entries] == [
        ("inserted", "1", "Inserted."),
        ("deleted", "4", "Deleted"),
    ]
    output = tmp_path / "reviewed.docx"
    render_reviewed_docx(review_document, [], output)
    assert output.exists()


def test_supported_revision_coverage_matches_text_controls(tmp_path: Path) -> None:
    # Given: a supported insertion whose visible text includes Word control characters.
    source = tmp_path / "revision-controls.docx"
    document = DocxDocument()
    document.add_paragraph("Plain ")
    document.save(source)
    _append_revision_controls(source)

    # When: ReviewKit projects effective text and the typed revision ledger.
    review_document = load_docx(source)

    # Then: tabs, line breaks, and carriage returns are compared as owned text, not wrapper counts.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.COMPLETE
    assert [(entry.kind.value, entry.revision_id, entry.text) for entry in review_document.revision_ledger.entries] == [
        ("inserted", "5", "A\tB\nC\nD"),
    ]


@pytest.mark.parametrize("revision_kind", ["pPrChange", "rPrChange"])
def test_property_revisions_remain_fail_closed_at_public_boundary(
    tmp_path: Path, revision_kind: str
) -> None:
    # Given: a DOCX carrying an unsupported property-change record.
    source = tmp_path / f"{revision_kind}.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.save(source)
    _append_property_revision(source, revision_kind)

    # When: ReviewKit parses the source and callers ask either renderer to publish it.
    review_document = load_docx(source)

    # Then: property revisions fail closed before either renderer creates an artifact.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    for renderer, filename in (
        (render_reviewed_docx, "reviewed.docx"),
        (render_corrected_docx, "corrected.docx"),
    ):
        output = tmp_path / filename
        with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
            renderer(review_document, [], output)
        assert not output.exists()


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


def test_mixed_supported_and_unsupported_revisions_fail_closed(tmp_path: Path) -> None:
    # Given: a source with one projected insertion and one unsupported move revision.
    source = tmp_path / "mixed-revisions.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.save(source)
    _append_revisions(source)
    _append_unsupported_move(source)

    # When: ReviewKit builds its effective input projection.
    review_document = load_docx(source)

    # Then: one supported entry cannot mask the unsupported source grammar.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    output = tmp_path / "reviewed.docx"
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], output)
    assert not output.exists()


def test_custom_xml_range_revisions_remain_fail_closed(tmp_path: Path) -> None:
    # Given: a supported insertion plus an unsupported Office custom XML range marker.
    source = tmp_path / "custom-xml-range.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.save(source)
    _append_custom_xml_range(source)

    # When: ReviewKit builds its effective input projection.
    review_document = load_docx(source)

    # Then: unsupported range grammar cannot be normalized by the text-aware comparison.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    for renderer, filename in (
        (render_reviewed_docx, "reviewed.docx"),
        (render_corrected_docx, "corrected.docx"),
    ):
        output = tmp_path / filename
        with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
            renderer(review_document, [], output)
        assert not output.exists()


def test_indirectly_nested_block_revision_remains_fail_closed(tmp_path: Path) -> None:
    # Given: a supported revision wrapper hiding an empty block through a customXml node.
    source = tmp_path / "nested-block-revision.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.save(source)
    _append_indirectly_nested_block_revision(source)

    # When: ReviewKit builds its effective input projection.
    review_document = load_docx(source)

    # Then: unsupported block-level revision grammar is refused before any output exists.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    reviewed_output = tmp_path / "reviewed.docx"
    corrected_output = tmp_path / "corrected.docx"
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], reviewed_output)
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_corrected_docx(review_document, [], corrected_output)
    assert not reviewed_output.exists()
    assert not corrected_output.exists()


def test_direct_block_revision_remains_fail_closed(tmp_path: Path) -> None:
    # Given: a supported revision wrapper containing a block-level paragraph directly.
    source = tmp_path / "direct-block-revision.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.save(source)
    _append_direct_block_revision(source)

    # When: ReviewKit builds its effective input projection.
    review_document = load_docx(source)

    # Then: direct block-level revision grammar is refused before either output exists.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    reviewed_output = tmp_path / "reviewed.docx"
    corrected_output = tmp_path / "corrected.docx"
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], reviewed_output)
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_corrected_docx(review_document, [], corrected_output)
    assert not reviewed_output.exists()
    assert not corrected_output.exists()


def test_duplicate_source_comment_ids_fail_closed(tmp_path: Path) -> None:
    # Given: a source whose two comment bodies claim the same Word identifier.
    source = tmp_path / "duplicate-comment-ids.docx"
    document = DocxDocument()
    first = document.add_paragraph()
    first_run = first.add_run("First.")
    document.add_comment(runs=first_run, text="First note.", author="A", initials="A")
    second = document.add_paragraph()
    second_run = second.add_run("Second.")
    document.add_comment(runs=second_run, text="Second note.", author="B", initials="B")
    document.save(source)
    _duplicate_second_comment_id(source)

    # When: ReviewKit reads the source and attempts to publish a review artifact.
    review_document = load_docx(source)
    output = tmp_path / "reviewed.docx"

    # Then: ambiguous source-comment identity is refused before output creation.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], output)
    assert not output.exists()


def test_orphan_source_comment_markers_fail_closed(tmp_path: Path) -> None:
    # Given: a source with balanced comment markers but no matching comment body.
    source = tmp_path / "orphan-comment-markers.docx"
    document = DocxDocument()
    document.add_paragraph("Plain text.")
    document.save(source)
    _append_orphan_comment_markers(source)

    # When: ReviewKit reads the source and attempts to publish a review artifact.
    review_document = load_docx(source)
    output = tmp_path / "reviewed.docx"

    # Then: orphan markers are refused before output creation.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], output)
    assert not output.exists()


def test_source_comment_without_reference_marker_fails_closed(tmp_path: Path) -> None:
    # Given: a source comment range whose reference marker was removed.
    source = tmp_path / "missing-comment-reference.docx"
    document = DocxDocument()
    paragraph = document.add_paragraph("Plain text.")
    document.add_comment(runs=paragraph.runs[0], text="Source note.", author="A", initials="A")
    document.save(source)
    _remove_comment_reference(source)

    # When: ReviewKit reads the source and attempts to publish a review artifact.
    review_document = load_docx(source)
    output = tmp_path / "reviewed.docx"

    # Then: a range without its reference is refused before output creation.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], output)
    assert not output.exists()


def test_duplicate_source_thread_paragraph_ids_fail_closed(tmp_path: Path) -> None:
    # Given: a threaded source where two comment bodies share one paragraph identity.
    source = tmp_path / "duplicate-thread-paragraph-ids.docx"
    document = DocxDocument()
    for label in ("First", "Second", "Third"):
        paragraph = document.add_paragraph(f"{label}.")
        document.add_comment(
            runs=paragraph.runs[0], text=f"{label} note.", author=label, initials=label[0]
        )
    document.save(source)
    _duplicate_thread_paragraph_id(source)

    # When: ReviewKit reads the source and attempts to publish a review artifact.
    review_document = load_docx(source)
    output = tmp_path / "reviewed.docx"

    # Then: ambiguous thread provenance is refused before output creation.
    assert review_document.revision_ledger.coverage == RevisionCoverageState.INCOMPLETE
    with pytest.raises(RevisionCoverageError, match="coverage is incomplete"):
        render_reviewed_docx(review_document, [], output)
    assert not output.exists()


def test_duplicate_source_thread_entries_fail_closed(tmp_path: Path) -> None:
    # Given: a threaded source with two sidecar entries for one child paragraph identity.
    source = tmp_path / "duplicate-thread-entries.docx"
    document = DocxDocument()
    for label in ("First", "Second"):
        paragraph = document.add_paragraph(f"{label}.")
        document.add_comment(
            runs=paragraph.runs[0], text=f"{label} note.", author=label, initials=label[0]
        )
    document.save(source)
    _duplicate_thread_comment_ex(source)

    # When: ReviewKit reads the source and attempts to publish a review artifact.
    review_document = load_docx(source)
    output = tmp_path / "reviewed.docx"

    # Then: duplicate sidecar identity is refused before output creation.
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


def _append_empty_nested_and_split_revisions(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    paragraph.append(_revision("ins", "In", "1"))
    paragraph.append(_revision("ins", "serted.", "1"))
    paragraph.append(etree.Element(f"{_W}ins", {f"{_W}id": "2", f"{_W}author": "Source reviewer"}))
    outer = etree.Element(f"{_W}ins", {f"{_W}id": "3", f"{_W}author": "Source reviewer"})
    outer.append(_revision("del", "Deleted", "4"))
    paragraph.append(outer)
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _append_revision_controls(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    insertion = etree.SubElement(
        paragraph,
        f"{_W}ins",
        {f"{_W}id": "5", f"{_W}author": "Source reviewer"},
    )
    run = etree.SubElement(insertion, f"{_W}r")
    first = etree.SubElement(run, f"{_W}t")
    first.text = "A"
    etree.SubElement(run, f"{_W}tab")
    second = etree.SubElement(run, f"{_W}t")
    second.text = "B"
    etree.SubElement(run, f"{_W}br")
    third = etree.SubElement(run, f"{_W}t")
    third.text = "C"
    etree.SubElement(run, f"{_W}cr")
    fourth = etree.SubElement(run, f"{_W}t")
    fourth.text = "D"
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _append_property_revision(path: Path, kind: str) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    attributes = {
        f"{_W}id": "7",
        f"{_W}author": "Source reviewer",
    }
    if kind == "pPrChange":
        properties = paragraph.find(f"{_W}pPr")
        if properties is None:
            properties = etree.Element(f"{_W}pPr")
            paragraph.insert(0, properties)
        etree.SubElement(properties, f"{_W}{kind}", attributes)
    else:
        run = paragraph.find(f"{_W}r")
        assert run is not None
        properties = run.find(f"{_W}rPr")
        if properties is None:
            properties = etree.Element(f"{_W}rPr")
            run.insert(0, properties)
        etree.SubElement(properties, f"{_W}{kind}", attributes)
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _append_unsupported_move(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    move_from = etree.Element(f"{_W}moveFrom", {f"{_W}id": "3"})
    run = etree.SubElement(move_from, f"{_W}r")
    text_node = etree.SubElement(run, f"{_W}t")
    text_node.text = "Moved."
    paragraph.append(move_from)
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _append_custom_xml_range(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    paragraph.append(etree.Element(f"{_W}customXmlInsRangeStart", {f"{_W}id": "9"}))
    paragraph.append(etree.Element(f"{_W}customXmlInsRangeEnd", {f"{_W}id": "9"}))
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _append_indirectly_nested_block_revision(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    insertion = etree.SubElement(
        paragraph,
        f"{_W}ins",
        {f"{_W}id": "6", f"{_W}author": "Source reviewer"},
    )
    custom_xml = etree.SubElement(insertion, f"{_W}customXml")
    etree.SubElement(custom_xml, f"{_W}p")
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _append_direct_block_revision(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    insertion = etree.SubElement(
        paragraph,
        f"{_W}ins",
        {f"{_W}id": "8", f"{_W}author": "Source reviewer"},
    )
    etree.SubElement(insertion, f"{_W}p")
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _duplicate_second_comment_id(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    comments_xml = next(data for info, data in entries if info.filename == "word/comments.xml")
    root = etree.fromstring(comments_xml)
    comments = root.findall(f"{_W}comment")
    assert len(comments) == 2
    comments[1].set(f"{_W}id", comments[0].get(f"{_W}id") or "0")
    revised_comments_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_comments_xml if info.filename == "word/comments.xml" else data,
            )


def _append_orphan_comment_markers(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    paragraph.extend(
        [
            etree.Element(f"{_W}commentRangeStart", {f"{_W}id": "99"}),
            etree.Element(f"{_W}commentRangeEnd", {f"{_W}id": "99"}),
            etree.Element(f"{_W}commentReference", {f"{_W}id": "99"}),
        ]
    )
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _remove_comment_reference(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    document_xml = next(data for info, data in entries if info.filename == "word/document.xml")
    root = etree.fromstring(document_xml)
    references = root.findall(f".//{_W}commentReference")
    assert len(references) == 1
    references[0].getparent().remove(references[0])
    revised_document_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_document_xml if info.filename == "word/document.xml" else data,
            )


def _duplicate_thread_paragraph_id(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    comments_xml = next(data for info, data in entries if info.filename == "word/comments.xml")
    root = etree.fromstring(comments_xml)
    comments = root.findall(f"{_W}comment")
    assert len(comments) == 3
    for comment, para_id in zip(comments, ("AAAA0001", "BBBB0002", "AAAA0001"), strict=True):
        paragraph = comment.find(f"{_W}p")
        assert paragraph is not None
        paragraph.set("{http://schemas.microsoft.com/office/word/2010/wordml}paraId", para_id)
    revised_comments_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    extended_xml = (
        b'<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
        b'<w15:commentEx w15:paraId="BBBB0002" w15:paraIdParent="AAAA0001"/>'
        b"</w15:commentsEx>"
    )
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_comments_xml if info.filename == "word/comments.xml" else data,
            )
        archive.writestr("word/commentsExtended.xml", extended_xml)


def _duplicate_thread_comment_ex(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    comments_xml = next(data for info, data in entries if info.filename == "word/comments.xml")
    root = etree.fromstring(comments_xml)
    comments = root.findall(f"{_W}comment")
    assert len(comments) == 2
    for comment, para_id in zip(comments, ("AAAA0001", "BBBB0002"), strict=True):
        paragraph = comment.find(f"{_W}p")
        assert paragraph is not None
        paragraph.set("{http://schemas.microsoft.com/office/word/2010/wordml}paraId", para_id)
    revised_comments_xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    extended_xml = (
        b'<w15:commentsEx xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
        b'<w15:commentEx w15:paraId="AAAA0001"/> '
        b'<w15:commentEx w15:paraId="BBBB0002" w15:paraIdParent="AAAA0001"/> '
        b'<w15:commentEx w15:paraId="BBBB0002" w15:paraIdParent="AAAA0001"/>'
        b"</w15:commentsEx>"
    )
    with ZipFile(path, "w") as archive:
        for info, data in entries:
            archive.writestr(
                info,
                revised_comments_xml if info.filename == "word/comments.xml" else data,
            )
        archive.writestr("word/commentsExtended.xml", extended_xml)


def _revision(kind: str, text: str, revision_id: str) -> etree._Element:
    revision = etree.Element(f"{_W}{kind}")
    revision.set(f"{_W}id", revision_id)
    revision.set(f"{_W}author", "Source reviewer")
    run = etree.SubElement(revision, f"{_W}r")
    text_node = etree.SubElement(run, f"{_W}{'t' if kind == 'ins' else 'delText'}")
    text_node.text = text
    return revision

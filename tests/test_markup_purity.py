from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pytest

from reviewkit import MarkupReport, has_comments, has_tracked_revisions, inspect_markup
from reviewkit.parser_docx import _contains_tracked_revisions

_XML_HEAD = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_W_NS = b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

# The drift set: revision kinds a legacy ``w:ins``/``w:del``-only detector misses.
_NON_INS_DEL_REVISIONS = [
    "moveFrom",
    "moveTo",
    "rPrChange",
    "pPrChange",
    "sectPrChange",
    "tblPrChange",
    "trPrChange",
    "tcPrChange",
    "cellIns",
    "cellDel",
    "cellMerge",
    "tblGridChange",
    "tblPrExChange",
    "numberingChange",
]


def _document_xml(inner: bytes) -> bytes:
    return _XML_HEAD + b"<w:document " + _W_NS + b"><w:body>" + inner + b"</w:body></w:document>"


def _comments_xml(inner: bytes) -> bytes:
    return _XML_HEAD + b"<w:comments " + _W_NS + b">" + inner + b"</w:comments>"


def _docx(tmp_path: Path, parts: dict[str, bytes], name: str = "d.docx") -> Path:
    path = tmp_path / name
    with ZipFile(path, "w") as bundle:
        for part_name, data in parts.items():
            bundle.writestr(part_name, data)
    return path


def test_clean_document_has_no_markup(tmp_path: Path) -> None:
    # Deliberately packed with the property wrappers a clean document always
    # carries (<w:sectPr>/<w:pPr>/<w:rPr>) to prove they never false-positive.
    path = _docx(
        tmp_path,
        {
            "word/document.xml": _document_xml(
                b"<w:p><w:pPr><w:sectPr/></w:pPr>"
                b"<w:r><w:rPr/><w:t>Ala ma kota.</w:t></w:r></w:p>"
            ),
            "word/styles.xml": _XML_HEAD + b"<w:styles " + _W_NS + b"><w:pPr/><w:rPr/></w:styles>",
        },
    )
    report = inspect_markup(path)
    assert report.is_clean
    assert report == MarkupReport()
    assert report.revision_parts == ()
    assert report.revision_kinds == ()
    assert report.comment_count == 0
    assert has_tracked_revisions(path) is False
    assert has_comments(path) is False


@pytest.mark.parametrize("kind", ["ins", "del"])
def test_tracked_change_ins_del_detected(tmp_path: Path, kind: str) -> None:
    inner = f'<w:{kind} w:id="1"><w:r><w:t>x</w:t></w:r></w:{kind}>'.encode()
    path = _docx(tmp_path, {"word/document.xml": _document_xml(inner)})
    report = inspect_markup(path)
    assert report.has_tracked_revisions
    assert report.revision_kinds == (kind,)
    assert report.revision_parts == ("word/document.xml",)
    assert has_tracked_revisions(path) is True


@pytest.mark.parametrize("element", _NON_INS_DEL_REVISIONS)
def test_move_format_table_revisions_detected(tmp_path: Path, element: str) -> None:
    # These are exactly the revisions the old ins/del-only grammar would miss.
    assert element not in {"ins", "del"}
    path = _docx(tmp_path, {"word/document.xml": _document_xml(f'<w:{element} w:id="7"/>'.encode())})
    report = inspect_markup(path)
    assert report.has_tracked_revisions, element
    assert element in report.revision_kinds


@pytest.mark.parametrize(
    "lookalike",
    [
        b'<w:insideH w:val="single"/>',  # table inner border, not <w:ins>
        b'<w:insideV w:val="single"/>',
        b"<w:tblPrEx><w:tblBorders/></w:tblPrEx>",  # table property exceptions, not tblPrExChange
        b"<w:sectPr/>",
        b"<w:pPr/>",
        b"<w:rPr/>",
        b"<w:tcPr/>",
        b"<w:trPr/>",
        b"<w:tblPr/>",
    ],
)
def test_lookalike_elements_are_not_revisions(tmp_path: Path, lookalike: bytes) -> None:
    path = _docx(tmp_path, {"word/document.xml": _document_xml(lookalike)})
    report = inspect_markup(path)
    assert not report.has_tracked_revisions
    assert has_tracked_revisions(path) is False


@pytest.mark.parametrize(
    "part",
    [
        "word/header1.xml",
        "word/footer2.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/glossary/document.xml",  # allowlist-based detectors miss this one
    ],
)
def test_revisions_in_non_body_parts_detected(tmp_path: Path, part: str) -> None:
    path = _docx(
        tmp_path,
        {
            "word/document.xml": _document_xml(b"<w:p><w:r><w:t>clean</w:t></w:r></w:p>"),
            part: _document_xml(b'<w:ins w:id="1"><w:r><w:t>x</w:t></w:r></w:ins>'),
        },
    )
    report = inspect_markup(path)
    assert report.has_tracked_revisions
    assert part in report.revision_parts


def test_comments_counted(tmp_path: Path) -> None:
    path = _docx(
        tmp_path,
        {
            "word/document.xml": _document_xml(b"<w:p><w:r><w:t>clean</w:t></w:r></w:p>"),
            "word/comments.xml": _comments_xml(
                b'<w:comment w:id="1"><w:p><w:r><w:t>a</w:t></w:r></w:p></w:comment>'
                b'<w:comment w:id="2"><w:p><w:r><w:t>b</w:t></w:r></w:p></w:comment>'
            ),
        },
    )
    report = inspect_markup(path)
    assert report.has_comments
    assert report.comment_count == 2
    assert not report.has_tracked_revisions
    assert has_comments(path) is True


def test_comment_reference_markers_are_not_comments(tmp_path: Path) -> None:
    # commentRangeStart/End and commentReference live in document.xml; only a
    # populated <w:comment> in comments.xml counts as a comment.
    path = _docx(
        tmp_path,
        {
            "word/document.xml": _document_xml(
                b'<w:commentRangeStart w:id="1"/>'
                b'<w:r><w:commentReference w:id="1"/></w:r>'
                b'<w:commentRangeEnd w:id="1"/>'
            )
        },
    )
    report = inspect_markup(path)
    assert report.comment_count == 0
    assert not report.has_comments


def test_inspect_reports_sorted_kinds_and_parts(tmp_path: Path) -> None:
    path = _docx(
        tmp_path,
        {
            "word/document.xml": _document_xml(b'<w:del w:id="1"/><w:ins w:id="2"/>'),
            "word/footnotes.xml": _document_xml(b'<w:moveTo w:id="3"/>'),
        },
    )
    report = inspect_markup(path)
    assert report.revision_kinds == ("del", "ins", "moveTo")
    assert report.revision_parts == ("word/document.xml", "word/footnotes.xml")


def test_unreadable_package_raises_rather_than_reporting_clean(tmp_path: Path) -> None:
    not_a_zip = tmp_path / "broken.docx"
    not_a_zip.write_bytes(b"this is not a zip")
    with pytest.raises(BadZipFile):
        inspect_markup(not_a_zip)
    with pytest.raises(BadZipFile):
        has_tracked_revisions(not_a_zip)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        inspect_markup(tmp_path / "nope.docx")


def test_parser_helper_uses_the_shared_full_grammar(tmp_path: Path) -> None:
    # A move revision with no w:ins/w:del: the parser's old ins/del-only grammar
    # would have reported False. It now delegates to the shared grammar.
    path = _docx(
        tmp_path,
        {"word/document.xml": _document_xml(b'<w:moveFrom w:id="3"><w:r><w:t>x</w:t></w:r></w:moveFrom>')},
    )
    assert _contains_tracked_revisions(path) is True


def test_parser_helper_fails_open_on_bad_package(tmp_path: Path) -> None:
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip")
    assert _contains_tracked_revisions(broken) is False

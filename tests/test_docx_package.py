"""Unit coverage for the deterministic-packaging primitive (reviewkit.docx_package)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document as DocxDocument

from reviewkit.docx_package import normalize_docx_timestamps


def _write_docx(path: Path) -> Path:
    docx = DocxDocument()
    docx.add_paragraph("Alpha beta gamma.")
    docx.save(path)
    return path


def test_normalize_pins_every_entry_timestamp_to_the_zip_epoch(tmp_path: Path) -> None:
    path = _write_docx(tmp_path / "doc.docx")
    # python-docx stamps the wall clock, so pre-normalization entries are NOT the epoch.
    with zipfile.ZipFile(path) as archive:
        assert any(info.date_time != (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    normalize_docx_timestamps(path)

    with zipfile.ZipFile(path) as archive:
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_normalize_preserves_names_order_and_content(tmp_path: Path) -> None:
    path = _write_docx(tmp_path / "doc.docx")
    with zipfile.ZipFile(path) as archive:
        before = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        order_before = [info.filename for info in archive.infolist()]

    normalize_docx_timestamps(path)

    with zipfile.ZipFile(path) as archive:
        after = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        order_after = [info.filename for info in archive.infolist()]
    assert order_after == order_before
    assert after == before
    # The package still opens as a valid DOCX after the rewrite.
    assert DocxDocument(str(path)).paragraphs[0].text == "Alpha beta gamma."


def test_normalize_is_idempotent(tmp_path: Path) -> None:
    path = _write_docx(tmp_path / "doc.docx")
    normalize_docx_timestamps(path)
    once = path.read_bytes()
    normalize_docx_timestamps(path)
    assert path.read_bytes() == once

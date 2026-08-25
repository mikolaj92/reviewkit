"""Deterministic DOCX packaging so identical review inputs yield byte-identical files.

The renderer already pins every *content* source of nondeterminism (revision dates,
comment dates, revision-id ordering), so identical inputs produce identical part XML.
The last remaining variable is the zip container itself: every writer that stamps
``zipfile`` entries with the wall-clock mtime (python-docx's ``Document.save`` among
them) makes an otherwise-identical ``.docx`` differ byte-for-byte on every run. This
module owns that final normalization so reviewkit's write paths keep the byte-for-byte
reproducibility their docstrings promise, without callers having to re-normalize the
output themselves.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

# The ZIP/DOS epoch (1980-01-01 00:00:00) is the smallest timestamp the zip format can
# represent, so it is the natural canonical value: stamping every entry with it removes
# the wall-clock mtime as a source of nondeterminism while staying a valid zip date that
# Word and every unzip tool accept.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _canonical_xml(data: bytes) -> bytes | None:
    try:
        root = etree.fromstring(
            data,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError:
        return None
    return etree.tostring(root, method="c14n", with_comments=True)


def restore_semantically_unchanged_xml_parts(
    source_path: str | Path,
    rendered_path: str | Path,
) -> None:
    """Restore source bytes for XML parts the renderer did not semantically change."""
    with zipfile.ZipFile(source_path) as source:
        original_parts = {
            name: source.read(name)
            for name in source.namelist()
            if name.endswith((".xml", ".rels"))
        }

    target = Path(rendered_path)
    with zipfile.ZipFile(target) as rendered:
        entries = [(info, rendered.read(info.filename)) for info in rendered.infolist()]

    changed = False
    restored_entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    for info, data in entries:
        original = original_parts.get(info.filename)
        canonical_original = _canonical_xml(original) if original is not None else None
        if (
            original is not None
            and data != original
            and canonical_original is not None
            and canonical_original == _canonical_xml(data)
        ):
            data = original
            changed = True
        restored_entries.append((info, data))

    if not changed:
        return
    with zipfile.ZipFile(target, "w") as output:
        for info, data in restored_entries:
            output.writestr(info, data)


def _deterministic_zipinfo(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """Copy ``info`` with its timestamp pinned to the ZIP epoch, all else preserved.

    Everything that already is deterministic -- the entry name, its per-part compression
    method, and the attribute/host-system metadata -- is carried across verbatim; only the
    ``date_time`` (the wall-clock value) is replaced, so the rewritten entry is byte-stable
    across runs without altering the package's structure or content.
    """
    stamped = zipfile.ZipInfo(info.filename, date_time=_ZIP_EPOCH)
    stamped.compress_type = info.compress_type
    stamped.external_attr = info.external_attr
    stamped.internal_attr = info.internal_attr
    stamped.create_system = info.create_system
    return stamped


def normalize_docx_timestamps(path: str | Path) -> None:
    """Rewrite the ``.docx`` package at ``path`` in place with fixed zip-entry timestamps.

    Entry order, names, content and per-part compression are preserved; only the wall-clock
    ``date_time`` of every entry is replaced with the fixed ZIP epoch. Use this after a
    write path that cannot stamp entries deterministically itself (notably python-docx's
    ``Document.save``) so the resulting package is reproducible byte-for-byte.
    """
    target = Path(path)
    with zipfile.ZipFile(target) as bundle:
        entries = [(info, bundle.read(info.filename)) for info in bundle.infolist()]
    with zipfile.ZipFile(target, "w") as out:
        for info, data in entries:
            out.writestr(_deterministic_zipinfo(info), data)

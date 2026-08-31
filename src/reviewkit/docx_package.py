"""Compatibility exports for neutral DOCX package operations owned by Docxtor."""

from docxtor import (
    normalize_docx_timestamps,
    restore_semantically_unchanged_xml_parts,
)

__all__ = [
    "normalize_docx_timestamps",
    "restore_semantically_unchanged_xml_parts",
]

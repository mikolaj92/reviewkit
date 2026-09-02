"""Neutral review-artifact preservation policy over Docxtor inventory."""

from pathlib import Path

from docxtor import DocxInventory, PackageRelationship, inventory_docx


class ReviewArtifactPreservationError(ValueError):
    pass


_REVIEW_ONLY_PREFIXES = ("word/comments", "word/people.xml")
_REVIEW_ONLY_RELATIONSHIP_KINDS = frozenset(
    {"comments", "commentsIds", "commentsExtended", "commentsExtensible", "people"}
)


def _is_review_only_package_part(name: str) -> bool:
    return (
        name.startswith(_REVIEW_ONLY_PREFIXES)
        or name.startswith("word/_rels/comments")
        or name == "word/_rels/people.xml.rels"
    )


def assert_docx_structure_preserved(
    source_docx: str | Path,
    transformed_docx: str | Path,
    *,
    phase: str,
) -> None:
    """Interpret Docxtor snapshots and fail on unrelated physical changes."""
    try:
        source = inventory_docx(Path(source_docx).read_bytes())
        transformed = inventory_docx(Path(transformed_docx).read_bytes())
    except OSError as exc:
        raise ReviewArtifactPreservationError(f"could not inspect DOCX package: {exc}") from exc
    if not source.parts or not transformed.parts:
        raise ReviewArtifactPreservationError(
            "could not inspect DOCX package: incomplete package inventory"
        )
    source_parts = {part.name: part for part in source.parts}
    transformed_parts = {part.name: part for part in transformed.parts}
    if phase == "reviewed":
        expected_removed = {"docProps/thumbnail.jpeg"}
        allowed_added = {"word/comments.xml"}
        allowed_changed = {
            "[Content_Types].xml",
            "_rels/.rels",
            "docProps/app.xml",
            "docProps/core.xml",
            "word/_rels/document.xml.rels",
            "word/document.xml",
            "word/comments.xml",
        }
        allowed_relationship_additions = {"comments"}
        allowed_relationship_removals: set[str] = set()
    elif phase == "corrected":
        expected_removed = {name for name in source_parts if _is_review_only_package_part(name)} | {
            "docProps/thumbnail.jpeg"
        }
        allowed_added = {name for name in transformed_parts if name.startswith("word/footer")}
        allowed_changed = {
            "[Content_Types].xml",
            "_rels/.rels",
            "docProps/app.xml",
            "docProps/core.xml",
            "word/_rels/document.xml.rels",
            "word/document.xml",
        }
        allowed_changed.update(
            name
            for name in transformed_parts
            if name.startswith("word/footer") or _is_review_only_package_part(name)
        )
        allowed_relationship_additions = {"footer"}
        allowed_relationship_removals = set(_REVIEW_ONLY_RELATIONSHIP_KINDS)
    else:
        raise ReviewArtifactPreservationError(f"unknown DOCX preservation phase: {phase!r}")
    missing = set(source_parts) - set(transformed_parts) - expected_removed
    if missing:
        raise ReviewArtifactPreservationError(
            "missing package parts: " + ", ".join(sorted(missing))
        )
    unexpected = set(transformed_parts) - set(source_parts) - allowed_added
    if unexpected:
        raise ReviewArtifactPreservationError(
            "unexpected package parts: " + ", ".join(sorted(unexpected))
        )
    for name in sorted(set(source_parts) & set(transformed_parts)):
        if (
            name not in allowed_changed
            and source_parts[name].sha256 != transformed_parts[name].sha256
        ):
            raise ReviewArtifactPreservationError(f"untouched package part changed: {name}")
    required = {"officeDocument", "core-properties", "extended-properties"}
    source_kinds = {
        _relationship_kind(item.relationship_type)
        for item in source.graph.relationships
        if item.source_part == ""
    }
    transformed_kinds = {
        _relationship_kind(item.relationship_type)
        for item in transformed.graph.relationships
        if item.source_part == ""
    }
    lost_required = (source_kinds & required) - transformed_kinds
    if lost_required:
        raise ReviewArtifactPreservationError(
            "package relationships were lost: " + ", ".join(sorted(lost_required))
        )
    source_relationships = {
        _relationship_tuple(item)
        for item in source.graph.relationships
        if item.source_part == "word/document.xml"
    }
    transformed_relationships = {
        _relationship_tuple(item)
        for item in transformed.graph.relationships
        if item.source_part == "word/document.xml"
    }
    missing_relationships = {
        item
        for item in source_relationships - transformed_relationships
        if _relationship_kind(item[1]) not in allowed_relationship_removals
    }
    if missing_relationships:
        raise ReviewArtifactPreservationError(
            "document relationships were lost: "
            + ", ".join(sorted(_format_relationship(item) for item in missing_relationships))
        )
    unexpected_relationships = {
        item
        for item in transformed_relationships - source_relationships
        if _relationship_kind(item[1]) not in allowed_relationship_additions
    }
    if unexpected_relationships:
        raise ReviewArtifactPreservationError(
            "unexpected document relationships: "
            + ", ".join(sorted(_format_relationship(item) for item in unexpected_relationships))
        )
    tracked = {"tbl", "sectPr", "hyperlink", "drawing", "numPr", "pStyle"}
    source_counts = _structure_counts(source, tracked)
    transformed_counts = _structure_counts(transformed, tracked)
    lost = {
        name: (source_counts[name], transformed_counts[name])
        for name in tracked
        if transformed_counts[name] < source_counts[name]
    }
    if lost:
        details = ", ".join(
            f"{name} {before}->{after}" for name, (before, after) in sorted(lost.items())
        )
        raise ReviewArtifactPreservationError("document structure was lost: " + details)


def _relationship_tuple(item: PackageRelationship) -> tuple[str, str, str, str]:
    return (
        item.relationship_id,
        item.relationship_type,
        item.target,
        "External" if item.external else "",
    )


def _structure_counts(snapshot: DocxInventory, names: set[str]) -> dict[str, int]:
    return {
        name: sum(
            1
            for surface in snapshot.surfaces
            if surface.part_name == "word/document.xml"
            and surface.element_qname
            and surface.element_qname.rsplit("}", 1)[-1] == name
            and surface.kind.value in {"xml_text", "xml_attribute", "text"}
        )
        for name in names
    }


def _relationship_kind(relationship_type: str) -> str:
    return relationship_type.rsplit("/", 1)[-1]


def _format_relationship(relationship: tuple[str, str, str, str]) -> str:
    relationship_id, relationship_type, target, _target_mode = relationship
    return f"{relationship_id}:{_relationship_kind(relationship_type)}->{target}"

from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from docx import Document as DocxDocument

from reviewkit.models import (
    ActionStatus,
    ReviewAction,
    ReviewActionType,
    ReviewFinding,
    ReviewLocator,
    ReviewReference,
    ReviewResult,
    ReviewScope,
)
from reviewkit.parser_docx import load_docx
from reviewkit.renderer_docx import render_corrected_docx, render_reviewed_docx

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


# The core contract: reviewed.docx must mark EVERY review action. Trackable edits land as
# w:ins/w:del tracked changes; advisory actions land as labelled Word comments. This table
# enumerates the expected marker for every ReviewActionType so a regression that silently
# stopped emitting one is caught. (tracked tags expected in document.xml, comment label)
_EVERY_ACTION_MARKER = [
    (ReviewActionType.REPLACE_TEXT, {"ins", "del"}, "SUGGESTION"),
    (ReviewActionType.REPLACE, {"ins", "del"}, "SUGGESTION"),
    (ReviewActionType.DELETE_TEXT, {"del"}, "SUGGESTION"),
    (ReviewActionType.DELETE, {"del"}, "SUGGESTION"),
    (ReviewActionType.INSERT_TEXT, {"ins"}, "SUGGESTION"),
    (ReviewActionType.INSERT_BEFORE, {"ins"}, "SUGGESTION"),
    (ReviewActionType.INSERT_AFTER, {"ins"}, "SUGGESTION"),
    (ReviewActionType.COMMENT, set(), "COMMENT"),
    (ReviewActionType.QUESTION, set(), "QUESTION"),
    (ReviewActionType.RISK, set(), "RISK"),
    (ReviewActionType.SUGGESTION, set(), "SUGGESTION"),
    (ReviewActionType.PRAISE, set(), "PRAISE"),
    (ReviewActionType.SUMMARY, set(), "SUMMARY"),
    (ReviewActionType.FLAG, set(), "COMMENT"),
]


@pytest.mark.parametrize(
    ("action_type", "tracked_tags", "label"),
    _EVERY_ACTION_MARKER,
    ids=[case[0].value for case in _EVERY_ACTION_MARKER],
)
def test_reviewed_docx_marks_every_action_type(
    tmp_path: Path,
    action_type: ReviewActionType,
    tracked_tags: set[str],
    label: str,
) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("The quick brown fox jumps.")
    docx.save(input_path)

    document = load_docx(input_path)
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=action_type,
        node_id="p1",
        original_text="fox",
        replacement_text="cat",
        comment="Reviewer note.",
    )

    reviewed_path = render_reviewed_docx(document, [action], tmp_path / "reviewed.docx")
    document_xml = _part_xml(reviewed_path, "word/document.xml")
    root = ElementTree.fromstring(document_xml)

    # Trackable edits produce the expected tracked-change markup; advisory actions must not.
    for tag in ("ins", "del"):
        found = root.find(f".//{_W}{tag}") is not None
        assert found is (tag in tracked_tags), f"{action_type.value}: unexpected w:{tag}={found}"

    # Every action - trackable or advisory - carries a labelled comment marker.
    comments = _comment_texts(reviewed_path)
    assert any(text.startswith(f"{label}:") for text in comments), (
        f"{action_type.value}: no comment labelled {label!r}; got {comments}"
    )


@pytest.mark.parametrize(
    ("status", "metadata", "label"),
    [
        (ActionStatus.CONFLICT, {}, "CONFLICT"),
        (ActionStatus.NEEDS_HUMAN_DECISION, {"blocked_from_corrected": True}, "HUMAN_DECISION"),
    ],
    ids=["conflict", "blocked_human_decision"],
)
def test_reviewed_docx_surfaces_unapplied_edits_as_labelled_comments(
    tmp_path: Path,
    status: ActionStatus,
    metadata: dict[str, object],
    label: str,
) -> None:
    # A writing edit that cannot be auto-applied (CONFLICT, or blocked from corrected) must
    # NOT become a silent tracked change - it surfaces as a labelled comment for a human.
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("The quick brown fox jumps.")
    docx.save(input_path)

    document = load_docx(input_path)
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.REPLACE,
        node_id="p1",
        original_text="fox",
        replacement_text="cat",
        reason="Contested wording.",
        status=status,
        metadata=metadata,
    )

    reviewed_path = render_reviewed_docx(document, [action], tmp_path / "reviewed.docx")
    root = ElementTree.fromstring(_part_xml(reviewed_path, "word/document.xml"))

    assert root.find(f".//{_W}ins") is None
    assert root.find(f".//{_W}del") is None
    comments = _comment_texts(reviewed_path)
    assert any(text.startswith(f"{label}:") for text in comments), (
        f"expected a comment labelled {label!r}; got {comments}"
    )


def test_reviewed_docx_surfaces_scope_level_conflict_as_a_comment(tmp_path: Path) -> None:
    # A section/document-scoped edit that ends up CONFLICT must still be surfaced. It used to
    # vanish (anchor returned None, and the scope-comment loops skip original_text actions),
    # losing the escalation for exactly the ambiguous, higher-scope case that needs a human.
    from reviewkit.document import ParagraphNode, ReviewDocument, SectionNode

    document = ReviewDocument(
        sections=[
            SectionNode(
                id="s1",
                paragraphs=[
                    ParagraphNode(id="p1", text="The quick brown fox jumps.", section_id="s1"),
                    ParagraphNode(id="p2", text="Another line entirely.", section_id="s1"),
                ],
            )
        ]
    )
    action = ReviewAction(
        scope=ReviewScope.SECTION,
        action_type=ReviewActionType.REPLACE,
        node_id="s1",
        original_text="fox",
        replacement_text="cat",
        reason="Ambiguous at section scope.",
        status=ActionStatus.CONFLICT,
    )

    reviewed_path = render_reviewed_docx(document, [action], tmp_path / "reviewed.docx")
    root = ElementTree.fromstring(_part_xml(reviewed_path, "word/document.xml"))

    # Surfaced as a labelled comment, never a silent tracked change.
    assert root.find(f".//{_W}ins") is None
    assert root.find(f".//{_W}del") is None
    comments = _comment_texts(reviewed_path)
    assert any(text.startswith("CONFLICT:") for text in comments), comments


def test_reviewed_docx_renders_delete_and_insert_text_revisions(tmp_path: Path) -> None:
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Alpha beta gamma.")
    docx.save(input_path)

    document = load_docx(input_path)
    paragraph = document.sections[0].paragraphs[0]
    actions = [
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.DELETE_TEXT,
            node_id=paragraph.id,
            original_text="beta",
            locator=ReviewLocator(node_id=paragraph.id, char_start=6, char_end=10),
            reason="Remove redundant word.",
            status=ActionStatus.NOT_APPLIED,
        ),
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.INSERT_AFTER,
            node_id=paragraph.id,
            original_text="gamma",
            replacement_text="!",
            locator=ReviewLocator(node_id=paragraph.id, char_start=11, char_end=16),
            reason="Add emphasis.",
            status=ActionStatus.NOT_APPLIED,
        ),
    ]

    reviewed_path = render_reviewed_docx(document, actions, tmp_path / "reviewed.docx")
    document_xml = _part_xml(reviewed_path, "word/document.xml")

    assert _revision_texts(document_xml, "del", "delText") == ["beta"]
    assert _revision_texts(document_xml, "ins", "t") == ["!"]


def test_insert_honors_locator_when_anchor_text_repeats(tmp_path: Path) -> None:
    # "beta" occurs twice; the locator disambiguates to the *second* one. The renderer
    # must honor the locator (like apply_action_to_text) instead of blindly inserting
    # before the first find() match, which would land the revision on the wrong "beta".
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("beta alpha beta gamma.")
    docx.save(input_path)

    document = load_docx(input_path)
    paragraph = document.sections[0].paragraphs[0]
    actions = [
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.INSERT_BEFORE,
            node_id=paragraph.id,
            original_text="beta",
            replacement_text="X",
            locator=ReviewLocator(node_id=paragraph.id, char_start=11, char_end=15),
            reason="Mark the second occurrence.",
            status=ActionStatus.NOT_APPLIED,
        ),
    ]

    reviewed_path = render_reviewed_docx(document, actions, tmp_path / "reviewed.docx")
    document_xml = _part_xml(reviewed_path, "word/document.xml")

    assert _accepted_paragraph_text(document_xml) == "beta alpha Xbeta gamma."


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


def test_reviewed_docx_comment_carries_a_references_line(tmp_path: Path) -> None:
    # An action's references are the citation carrier for downstream users: the comment body
    # in word/comments.xml must include a "References:" line listing each reference by label
    # (falling back to source when no label is set).
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("The quick brown fox jumps.")
    docx.save(input_path)

    document = load_docx(input_path)
    action = ReviewAction(
        scope=ReviewScope.PARAGRAPH,
        action_type=ReviewActionType.COMMENT,
        node_id="p1",
        comment="Grounded observation.",
        references=[
            ReviewReference(source="KC", label="art. 385(1)"),
            ReviewReference(source="unlabelled-source"),
        ],
    )

    reviewed_path = render_reviewed_docx(document, [action], tmp_path / "reviewed.docx")

    comments = _comment_texts(reviewed_path)
    assert any(
        "References: art. 385(1), unlabelled-source" in text for text in comments
    ), comments


def test_reviewed_docx_interleaves_several_tracked_edits_in_one_paragraph(tmp_path: Path) -> None:
    # Several trackable edits landing on ONE paragraph must interleave correctly: each edit's
    # w:del/w:ins pair sits inside its own commentRangeStart/commentRangeEnd, untouched text
    # survives between them, and every revision carries a fresh id (strictly increasing in
    # document order for edits applied left to right).
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("Alpha beta gamma delta.")
    docx.save(input_path)

    document = load_docx(input_path)
    actions = [
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.REPLACE,
            node_id="p1",
            original_text="beta",
            replacement_text="B",
            reason="First edit.",
            status=ActionStatus.NOT_APPLIED,
        ),
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.DELETE_TEXT,
            node_id="p1",
            original_text=" gamma",
            reason="Second edit.",
            status=ActionStatus.NOT_APPLIED,
        ),
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.INSERT_AFTER,
            node_id="p1",
            original_text="delta",
            replacement_text="!",
            reason="Third edit.",
            status=ActionStatus.NOT_APPLIED,
        ),
    ]

    reviewed_path = render_reviewed_docx(document, actions, tmp_path / "reviewed.docx")
    document_xml = _part_xml(reviewed_path, "word/document.xml")
    root = ElementTree.fromstring(document_xml)
    paragraph_xml = root.find(f".//{_W}p")
    assert paragraph_xml is not None

    # Exact interleaving: kept runs between the edits, each edit wrapped in its own
    # comment range (replace = del+ins, delete = del only, insert = ins only).
    assert [child.tag for child in paragraph_xml] == [
        f"{_W}r",  # "Alpha "
        f"{_W}commentRangeStart",
        f"{_W}del",  # "beta"
        f"{_W}ins",  # "B"
        f"{_W}commentRangeEnd",
        f"{_W}r",  # comment reference
        f"{_W}commentRangeStart",
        f"{_W}del",  # " gamma"
        f"{_W}commentRangeEnd",
        f"{_W}r",  # comment reference
        f"{_W}r",  # " delta"
        f"{_W}commentRangeStart",
        f"{_W}ins",  # "!"
        f"{_W}commentRangeEnd",
        f"{_W}r",  # comment reference
        f"{_W}r",  # "."
    ]
    assert _revision_texts(document_xml, "del", "delText") == ["beta", " gamma"]
    assert _revision_texts(document_xml, "ins", "t") == ["B", "!"]

    # Every revision gets a fresh id: strictly increasing in document order.
    revision_ids = [
        int(child.get(f"{_W}id") or -1)
        for child in paragraph_xml
        if child.tag in {f"{_W}del", f"{_W}ins"}
    ]
    assert len(revision_ids) == 4
    assert all(earlier < later for earlier, later in zip(revision_ids, revision_ids[1:]))

    # Comment ranges pair up: starts and ends carry the same ids in the same order,
    # one distinct comment per edit.
    start_ids = [
        child.get(f"{_W}id")
        for child in paragraph_xml
        if child.tag == f"{_W}commentRangeStart"
    ]
    end_ids = [
        child.get(f"{_W}id") for child in paragraph_xml if child.tag == f"{_W}commentRangeEnd"
    ]
    assert start_ids == end_ids
    assert len(set(start_ids)) == 3


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


def test_reviewed_docx_comment_dates_are_deterministic_by_default(tmp_path: Path) -> None:
    # python-docx stamps comment w:date with wall-clock time; without the override the
    # comments.xml part differs on every run. Two renders of identical inputs must match.
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

    first_comments = _part_xml(first, "word/comments.xml")
    second_comments = _part_xml(second, "word/comments.xml")
    assert first_comments == second_comments

    comment = ElementTree.fromstring(first_comments).find(f".//{_W}comment")
    assert comment is not None
    assert comment.get(f"{_W}date") == "1970-01-01T00:00:00+00:00"


def test_reviewed_docx_comment_uses_explicit_revision_timestamp(tmp_path: Path) -> None:
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

    comment = ElementTree.fromstring(_part_xml(reviewed_path, "word/comments.xml")).find(
        f".//{_W}comment"
    )
    assert comment is not None
    assert comment.get(f"{_W}date") == "2026-07-03T09:30:00+00:00"


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


def test_reviewed_and_corrected_artifacts_are_byte_reproducible(tmp_path: Path) -> None:
    # Determinism is a core contract: identical document + actions must yield byte-identical
    # artifacts so downstream diffing/caching stays stable. A nondeterministic comment id,
    # revision id, dict ordering or timestamp would break this with no other failing test.
    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    docx.add_paragraph("The quick brown fox jumps.")
    docx.save(input_path)

    document = load_docx(input_path)
    actions = [
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.REPLACE_TEXT,
            node_id="p1",
            original_text="fox",
            replacement_text="cat",
            comment="Prefer cat.",
            apply_hint=True,
        ),
        ReviewAction(
            scope=ReviewScope.PARAGRAPH,
            action_type=ReviewActionType.COMMENT,
            node_id="p1",
            comment="Advisory note.",
        ),
    ]

    def reviewed_parts(suffix: str) -> tuple[bytes, bytes]:
        path = render_reviewed_docx(document, actions, tmp_path / f"reviewed-{suffix}.docx")
        with ZipFile(path) as archive:
            return archive.read("word/document.xml"), archive.read("word/comments.xml")

    first_document, first_comments = reviewed_parts("a")
    second_document, second_comments = reviewed_parts("b")
    assert first_document == second_document
    assert first_comments == second_comments

    def corrected_document(suffix: str) -> bytes:
        path = render_corrected_docx(document, actions, tmp_path / f"corrected-{suffix}.docx")
        with ZipFile(path) as archive:
            return archive.read("word/document.xml")

    assert corrected_document("a") == corrected_document("b")

    result = ReviewResult(
        findings=[ReviewFinding(node_id="p1", title="Word choice", description="fox -> cat")],
        actions=actions,
    )
    first_json = result.save_json(tmp_path / "report-a.json").read_bytes()
    second_json = result.save_json(tmp_path / "report-b.json").read_bytes()
    assert first_json == second_json


def test_precise_comment_anchor_survives_opaque_segment_before_the_quote(tmp_path: Path) -> None:
    # A comment carrying original_text anchors to just the quoted span. When an opaque inline
    # object (here a line break) precedes the quote, _mark_text_comment must count its visible
    # width the same way _visible_text does; otherwise the two coordinate systems desync, the
    # anchor indexes come back empty, and the comment silently degrades to whole-paragraph.
    from docx.oxml import OxmlElement

    input_path = tmp_path / "input.docx"
    docx = DocxDocument()
    paragraph = docx.add_paragraph()
    paragraph.add_run("Ala")
    break_run = paragraph.add_run()
    break_run._r.append(OxmlElement("w:br"))
    paragraph.add_run("beta target here")
    docx.save(input_path)

    document = load_docx(input_path)
    node = document.sections[0].paragraphs[0]
    assert node.text == "Ala\nbeta target here"

    reviewed_path = render_reviewed_docx(
        document,
        [
            ReviewAction(
                scope=ReviewScope.PARAGRAPH,
                action_type=ReviewActionType.RISK,
                node_id=node.id,
                original_text="target",
                comment="Ambiguous term.",
            )
        ],
        tmp_path / "reviewed.docx",
    )

    paragraph_xml = ElementTree.fromstring(
        _part_xml(reviewed_path, "word/document.xml")
    ).find(f".//{_W}p")
    assert paragraph_xml is not None
    # Only "target" is inside the comment range - not the whole paragraph.
    assert _commented_run_text(paragraph_xml) == "target"


def _commented_run_text(paragraph_xml: ElementTree.Element) -> str:
    inside = False
    parts: list[str] = []
    for child in paragraph_xml:
        if child.tag == f"{_W}commentRangeStart":
            inside = True
        elif child.tag == f"{_W}commentRangeEnd":
            inside = False
        elif inside and child.tag == f"{_W}r":
            parts.extend(text.text or "" for text in child.iter(f"{_W}t"))
    return "".join(parts)


def _part_xml(path: Path, member: str) -> str:
    with ZipFile(path) as archive:
        return archive.read(member).decode()


def _comment_texts(path: Path) -> list[str]:
    root = ElementTree.fromstring(_part_xml(path, "word/comments.xml"))
    return ["".join(comment.itertext()) for comment in root.findall(f".//{_W}comment")]


def _accepted_paragraph_text(xml: str) -> str:
    # Visible text of the first paragraph with all insertions accepted: every w:t in
    # document order (w:delText under w:del is a different tag, so deletions drop out).
    root = ElementTree.fromstring(xml)
    paragraph = root.find(f".//{_W}p")
    assert paragraph is not None
    return "".join(text.text or "" for text in paragraph.iter(f"{_W}t"))


def _revision_texts(xml: str, revision_tag: str, text_tag: str) -> list[str]:
    root = ElementTree.fromstring(xml)
    return [
        "".join(element.itertext())
        for element in root.findall(f".//{_W}{revision_tag}")
        if element.find(f".//{_W}{text_tag}") is not None
    ]

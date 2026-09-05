from typing import Any

from reviewkit import DocumentParser, ReviewDocument, TextDocumentParser, parse_text
from reviewkit import review as review_module


def test_text_parser_builds_stable_four_level_tree() -> None:
    source = "# Introduction\n\nFirst sentence. Second sentence!\n\n## Result\n\nDone."

    document = parse_text(source, source_name="paper.md")

    assert document.metadata == {
        "source_format": "markdown",
        "source_name": "paper.md",
        "paragraph_count": "2",
    }
    assert document.id == "document"
    assert [section.id for section in document.sections] == ["s1", "s2"]
    assert [section.title for section in document.sections] == ["Introduction", "Result"]
    assert [section.locator for section in document.sections] == [
        "text:section:0",
        "text:section:1",
    ]
    paragraphs = list(document.iter_paragraphs())
    assert [paragraph.id for paragraph in paragraphs] == ["p1", "p2"]
    assert [paragraph.locator for paragraph in paragraphs] == [
        "text:paragraph:0",
        "text:paragraph:1",
    ]
    assert [sentence.text for sentence in paragraphs[0].sentences] == [
        "First sentence.",
        "Second sentence!",
    ]
    assert [sentence.locator for sentence in paragraphs[0].sentences] == [
        "text:paragraph:0:sentence:0",
        "text:paragraph:0:sentence:1",
    ]
    assert paragraphs[0].sentences[1].char_start == 16
    assert paragraphs[0].sentences[1].char_end == 32


def test_markdown_headings_do_not_require_blank_lines() -> None:
    document = parse_text("# First\nParagraph one.\n## Second\nParagraph two.")

    assert [section.title for section in document.sections] == ["First", "Second"]
    assert [paragraph.text for paragraph in document.iter_paragraphs()] == [
        "Paragraph one.",
        "Paragraph two.",
    ]


def test_review_source_passes_the_parser_tree_to_format_neutral_review(monkeypatch) -> None:
    parser = TextDocumentParser(source_name="note.txt")
    captured: dict[str, Any] = {}

    def fake_review_tree(document, profile_path, llm, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(document=document, profile_path=profile_path, llm=llm, kwargs=kwargs)
        return "result"

    monkeypatch.setattr(review_module, "review_tree", fake_review_tree)
    llm = object()

    result = review_module.review_source(
        "A sentence.", parser, "profile", llm, context_provider="context"
    )

    assert result == "result"
    assert captured["document"].metadata["source_name"] == "note.txt"
    assert captured["profile_path"] == "profile"
    assert captured["llm"] is llm
    assert captured["kwargs"] == {"context_provider": "context"}


def test_text_parser_is_a_public_document_parser_adapter() -> None:
    parser: DocumentParser = TextDocumentParser(source_name="note.txt")

    document = parser.parse("One paragraph.\n\nAnother paragraph.")

    assert isinstance(document, ReviewDocument)
    assert document.metadata["source_format"] == "text"
    assert document.metadata["source_name"] == "note.txt"
    assert len(document.sections) == 1
    assert len(list(document.iter_paragraphs())) == 2

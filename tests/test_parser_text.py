from reviewkit import DocumentParser, ReviewDocument, TextDocumentParser, parse_text


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


def test_text_parser_is_a_public_document_parser_adapter() -> None:
    parser: DocumentParser = TextDocumentParser(source_name="note.txt")

    document = parser.parse("One paragraph.\n\nAnother paragraph.")

    assert isinstance(document, ReviewDocument)
    assert document.metadata["source_format"] == "text"
    assert document.metadata["source_name"] == "note.txt"
    assert len(document.sections) == 1
    assert len(list(document.iter_paragraphs())) == 2

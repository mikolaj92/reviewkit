from pathlib import Path


def test_reviewkit_has_no_physical_docx_implementation() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "reviewkit"
    forbidden = (
        "from zipfile",
        "import zipfile",
        "xml.etree",
        "from lxml",
        "import lxml",
        "docx.oxml",
        "from docx ",
        "from docx.",
    )
    offenders = []
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if any(token in source for token in forbidden):
            offenders.append(path.relative_to(root).as_posix())
    assert offenders == []

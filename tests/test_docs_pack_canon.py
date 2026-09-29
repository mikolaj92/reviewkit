import importlib.util
from pathlib import Path
from types import ModuleType


def _sketch() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "examples" / "host_pack_review.py"
    spec = importlib.util.spec_from_file_location("host_pack_review", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_pack_is_the_public_pack_shape() -> None:
    pack = _sketch().load_example_pack()
    assert pack.ontology.function_ids() == {"opening", "conflict", "resolution"}
    assert pack.units["unit-opening"].force == "binding"
    assert all(rule.function_id in pack.ontology.function_ids() for rule in pack.rules)


def test_host_sketch_names_then_judges_and_exposes_covered_gaps() -> None:
    findings, actions, state, pack = _sketch().review_sample()
    assert state.covered() == {"opening": ["p1.s1"]}
    gaps = pack.ontology.function_ids() - set(state.covered())
    assert gaps == {"conflict", "resolution"}
    assert [finding.title for finding in findings] == ["missing"]
    assert findings[0].dimension is None
    assert actions


def test_docs_name_pack_and_two_scans_not_stale_host_apis() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "host-integration.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    release = (root / "docs" / "releases" / "0.24.0.md").read_text(encoding="utf-8")
    for text in (readme, guide, changelog, release):
        assert "Pack" in text
        assert "DecisionClient" in text
        assert "covered()" in text
        assert "required-clauses.md" not in text
        assert "ParagraphInserter" not in text
        assert "InsertionValidator" not in text
    example_blobs = [
        path.read_text(encoding="utf-8")
        for path in (root / "examples").rglob("*")
        if path.is_file() and path.suffix in {".md", ".toml", ".py", ".json"}
    ]
    docs = f"{readme}\n{guide}\n{changelog}\n{release}\n{''.join(example_blobs)}"
    for token in ("RODO", "PKE", "UODO", "Basal", "Qwen"):
        assert all(token not in blob for blob in example_blobs)
        if token in {"Basal", "Qwen"}:
            continue
        assert token not in docs

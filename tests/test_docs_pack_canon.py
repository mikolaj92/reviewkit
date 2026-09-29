import importlib.util
import json
from pathlib import Path
from types import ModuleType

from reviewkit import Pack, load_profile


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
    # Close / missing does not call LLMClient.complete_json (act is for change/delete/insert).
    assert actions == []


_SCIENTIFIC_FUNCTIONS = {
    "abstract",
    "research_question",
    "related_work",
    "methods",
    "results",
    "discussion",
    "limitations",
    "citations",
    "novelty_claim",
    "reproducibility",
}


def test_scientific_paper_pack_model_validate() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (root / "examples" / "packs" / "scientific_paper.json").read_text(encoding="utf-8")
    )
    pack = Pack.model_validate(payload)
    assert pack.ontology.function_ids() == _SCIENTIFIC_FUNCTIONS
    assert {rule.kind for rule in pack.rules} == {"label", "defect", "close"}
    assert all(rule.function_id in _SCIENTIFIC_FUNCTIONS for rule in pack.rules)
    assert all(
        rule.source_unit_id is None or rule.source_unit_id in pack.units for rule in pack.rules
    )
    for kind, scope in (("label", "fragment"), ("defect", "fragment"), ("close", "document")):
        assert all(rule.scope == scope for rule in pack.rules if rule.kind == kind)
    assert pack.units["unit-citation-provenance"].force == "heuristic"
    assert pack.units["unit-consort"].url
    assert pack.units["unit-primer-information-theory"].url
    assert pack.units["unit-primer-scientific-method"].url
    uncited = set(pack.units) - {rule.source_unit_id for rule in pack.rules if rule.source_unit_id}
    assert "unit-primer-information-theory" in uncited
    assert "unit-primer-cargo-cult" in uncited


def test_scientific_reviewer_profile_is_behavior_only() -> None:
    root = Path(__file__).resolve().parents[1]
    profile = load_profile(root / "examples" / "profiles" / "scientific.reviewer")
    assert profile.language == "en"
    assert profile.reviewer_role == "peer reviewer"
    assert profile.action_policy.require_llm_apply_hint is True
    assert "ontology" not in profile.markdown_files
    assert "functions" not in profile.model_dump()
    dumped = " ".join(profile.markdown_files.values()).lower()
    assert "function_id" not in dumped
    assert "source_unit" not in dumped


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
    assert "## Platforms" in readme
    assert "## Platforms" in guide
    assert "scientific_paper.json" in readme
    assert "scientific_paper.json" in guide
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

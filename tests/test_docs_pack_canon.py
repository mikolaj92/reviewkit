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


def _scientific_sketch() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "examples" / "scientific_paper_review.py"
    spec = importlib.util.spec_from_file_location("scientific_paper_review", path)
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
    assert [finding.title for finding in findings] == ["change", "missing"]
    assert findings[0].dimension is None
    assert findings[1].dimension is None
    assert actions


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
    pack = Pack.model_validate_json(
        (root / "examples" / "packs" / "scientific_paper.json").read_text(encoding="utf-8")
    )
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


def test_scientific_paper_pack_runs_name_judge_act_on_egg_fixture() -> None:
    findings, actions, state, pack, llm = _scientific_sketch().review_egg_paper()
    tagged = {node_id for nodes in state.covered().values() for node_id in nodes}
    assert any("." in node_id for node_id in tagged)
    assert "p1" in tagged
    assert "s1" in tagged
    assert "document" in tagged
    assert "abstract" in state.covered()
    assert "novelty_claim" in state.covered()
    assert "citations" in state.covered()
    assert "results" in state.covered()
    gaps = pack.ontology.function_ids() - set(state.covered())
    assert "methods" in gaps
    assert "research_question" in gaps
    titles = {finding.title for finding in findings}
    assert "change" in titles
    assert "missing" in titles
    assert llm.calls
    assert any(getattr(call.schema, "__name__", "") == "ActionText" for call in llm.calls)
    assert any(action.replacement_text for action in actions)


def test_docs_name_pack_and_two_scans_not_stale_host_apis() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    guide = (root / "docs" / "host-integration.md").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    release = (root / "docs" / "releases" / "0.24.1.md").read_text(encoding="utf-8")
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
    assert "pack=None" not in readme
    assert "pack=None" not in guide
    assert "model_validate_json" in readme
    phrase = "privacy notice or a newspaper article"
    for text in (readme, guide, changelog, release):
        assert phrase in text
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


def test_core_has_no_product_or_statute_domain() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "reviewkit"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in ("RODO", "PKE", "UODO", "Temida"):
            assert token not in text, f"{path} names {token}"

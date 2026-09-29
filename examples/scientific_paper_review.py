"""Stress-test the scientific paper Pack: name → judge → act.

Same reading order as a reviewer: every sentence, then paragraph, section,
and document. Plugins are MockDecisionClient and MockLLMClient. Takt is a
stand-in so the sketch runs without compiling Mojo.

Planted defects in ``examples/papers/egg-low-quality.md``: overclaim in the
lead, fake-looking citation, unsupported result claim, missing methods.

Run from the repo root:

    uv run python examples/scientific_paper_review.py
"""

from __future__ import annotations

from pathlib import Path

from reviewkit import (
    MockDecisionClient,
    MockLLMClient,
    Pack,
    TaktReviewer,
    load_profile,
    parse_text,
)
from reviewkit.document import ReviewDocument
from reviewkit.homeostat import scope_to_layer_index
from reviewkit.models import ReviewAction, ReviewFinding
from reviewkit.pack import Rule, judge_rules
from reviewkit.plant import ReviewDocumentPlant
from reviewkit.profile import ReviewProfile
from reviewkit.state import ReviewState
from reviewkit.takt_types import TaktDecision

_EXAMPLES = Path(__file__).resolve().parent
PACK_PATH = _EXAMPLES / "packs" / "scientific_paper.json"
PROFILE_PATH = _EXAMPLES / "profiles" / "scientific.reviewer"
PAPER_PATH = _EXAMPLES / "papers" / "egg-low-quality.md"

# Defects a reviewer would rewrite on this fixture (act path). Other fragment
# rules stay keep so the script stays small; absence still closes on the document.
_ACT_RULES = frozenset(
    {
        "defect-overclaim",
        "defect-hallucinated-refs",
        "defect-claim-evidence",
        "defect-claim-evidence-results",
    }
)


class _ActuatingTakt:
    """Stand-in so the sketch runs without compiling Takt. Hosts use TaktClient."""

    def evaluate(self, **kwargs: object) -> TaktDecision:
        nodes = kwargs.get("plant_nodes") or ()
        node_id = nodes[0].id if nodes else "n"
        return TaktDecision(outcome="actuation", node_id=node_id)


def load_scientific_pack() -> Pack:
    return Pack.model_validate_json(PACK_PATH.read_text(encoding="utf-8"))


def load_egg_paper() -> ReviewDocument:
    return parse_text(PAPER_PATH.read_text(encoding="utf-8"), source_name=PAPER_PATH.name)


def _name_from_text(text: str) -> set[str]:
    """Scripted namer for this fixture only — not a model and not domain core."""
    lowered = text.lower()
    named: set[str] = set()
    if "we prove" in lowered or "first time" in lowered or "definitive solution" in lowered:
        named.update({"abstract", "novelty_claim"})
    if "journal of imaginary" in lowered or "doi:10.0000" in lowered:
        named.add("citations")
    if "highly significant" in lowered or "method is proven" in lowered:
        named.update({"results", "novelty_claim"})
    return named


def _node_text(node: object) -> str:
    inner = getattr(node, "inner", node)
    return str(getattr(inner, "text", "") or "")


def script_egg_decision_answers(
    document: ReviewDocument, pack: Pack, profile: ReviewProfile
) -> list[dict]:
    """Build MockDecisionClient answers in name-then-judge order."""
    plant = ReviewDocumentPlant(document, scope_layers=scope_to_layer_index(profile))
    enabled = set(profile.review_pipeline)
    answers: list[dict] = []
    tags: dict[str, list[str]] = {}
    covered: dict[str, list[str]] = {}

    for node in plant.sequential_scan():
        scope = node.scope()
        if scope is None or scope not in enabled:
            continue
        text = _node_text(node)
        if not text.strip():
            continue
        named = sorted(_name_from_text(text))
        answers.append({function_id: True for function_id in named})
        if named:
            tags[node.id] = named
            for function_id in named:
                nodes = covered.setdefault(function_id, [])
                if node.id not in nodes:
                    nodes.append(node.id)

    for node in plant.sequential_scan():
        scope = node.scope()
        if scope is None or scope not in enabled:
            continue
        function_ids = tags.get(node.id, [])
        for rule in judge_rules(pack, scope, function_ids, covered):
            answers.append(_answer_for_rule(rule))
    return answers


def _answer_for_rule(rule: Rule) -> dict:
    if rule.kind == "close" or rule.when == "function_absent":
        return {"present": False}
    if rule.id in _ACT_RULES:
        return {"verdict": {"value": "change", "confidence": 0.95}}
    return {"verdict": "keep"}


def review_egg_paper() -> tuple[
    list[ReviewFinding], list[ReviewAction], ReviewState, Pack, MockLLMClient
]:
    pack = load_scientific_pack()
    profile = load_profile(PROFILE_PATH)
    document = load_egg_paper()
    answers = script_egg_decision_answers(document, pack, profile)
    n_act = sum(
        1
        for item in answers
        if isinstance(item.get("verdict"), dict) and item["verdict"].get("value") == "change"
    )
    decision = MockDecisionClient(answers=answers)
    llm = MockLLMClient(
        responses=[{"replacement_text": "Hedge this claim to the evidence shown."}] * n_act
    )
    findings, actions, state = TaktReviewer(
        profile=profile,
        llm=llm,
        pack=pack,
        decision=decision,
        takt_client=_ActuatingTakt(),
    ).review(document)
    return findings, actions, state, pack, llm


def main() -> None:
    findings, actions, state, pack, llm = review_egg_paper()
    covered = state.covered()
    gaps = pack.ontology.function_ids() - set(covered)
    print("covered:", {key: value for key, value in sorted(covered.items())})
    print("gaps:", sorted(gaps))
    print("findings:", [finding.title for finding in findings])
    print("actions:", len(actions), "act_calls:", len(llm.calls))


if __name__ == "__main__":
    main()

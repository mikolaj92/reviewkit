"""Host integration sketch: construct or load Pack as a typed object.

This is what a host does. ReviewKit is a generic review process. The same
engine reviews a privacy notice or a newspaper article; only Pack content
changes. ReviewKit does not build the Pack, does not ship a model runtime,
and does not treat profile markdown as the review payload. Hosts construct
Pack / Ontology / Rule / SourceUnit in Python, or load a file once with
Pack.model_validate_json. The review call site receives Pack,
DecisionClient, and LLMClient instances.

Run from the repo root:

    uv run python examples/host_pack_review.py
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
from reviewkit.takt_types import TaktDecision

_EXAMPLES = Path(__file__).resolve().parent
PACK_PATH = _EXAMPLES / "packs" / "story.json"
PROFILE_PATH = _EXAMPLES / "profiles" / "story.teacher"


class _StableTakt:
    """Stand-in so the sketch runs without compiling Takt. Hosts use TaktClient."""

    def evaluate(self, **kwargs: object) -> TaktDecision:
        return TaktDecision(outcome="stable", node_id="n")


def load_example_pack() -> Pack:
    return Pack.model_validate_json(PACK_PATH.read_text(encoding="utf-8"))


def review_sample() -> tuple:
    pack = load_example_pack()
    profile = load_profile(PROFILE_PATH)
    document = parse_text("Once upon a time there was a storm.")
    decision = MockDecisionClient(
        answers=[
            {"opening": True},
            {},
            {},
            {},
            {"verdict": {"value": "change", "confidence": 0.95}},
            {"present": False},
        ]
    )
    llm = MockLLMClient(responses=[{"replacement_text": "Then a conflict appeared."}])
    findings, actions, state = TaktReviewer(
        profile=profile,
        llm=llm,
        pack=pack,
        decision=decision,
        takt_client=_StableTakt(),
    ).review(document)
    return findings, actions, state, pack


def main() -> None:
    findings, actions, state, pack = review_sample()
    covered = state.covered()
    gaps = pack.ontology.function_ids() - set(covered)
    print("covered:", covered)
    print("gaps:", sorted(gaps))
    print("findings:", [finding.title for finding in findings])
    print("actions:", len(actions))


if __name__ == "__main__":
    main()

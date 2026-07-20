"""Map ReviewProfile to takt 0.2.0 layer specs (JSON boundary).

Each review scope becomes one cascade layer. Thresholds come from the
profile action policy and conservative fail-closed defaults.
"""

from __future__ import annotations

from reviewkit.profile import ReviewProfile
from reviewkit.models import ReviewScope
from reviewkit.takt_types import LayerSpec


def profile_to_layer_specs(profile: ReviewProfile) -> dict[ReviewScope, LayerSpec]:
    """Return one LayerSpec per enabled scope in review pipeline order."""
    policy = profile.resolved_action_policy()
    pipeline = profile.review_pipeline

    specs: dict[ReviewScope, LayerSpec] = {}
    for idx, scope in enumerate(pipeline):
        tolerance = 0.5
        if policy.max_severity_for_auto_apply in ("low", "info"):
            tolerance = 0.25

        specs[scope] = LayerSpec(
            layer=idx,
            tolerance=tolerance,
            cutoff=0.05,
            min_confidence=max(0.1, float(policy.min_confidence_for_auto_apply or 0.6)),
            entropy_threshold=0.30,
        )
    return specs


def build_layer_specs(profile: ReviewProfile) -> list[LayerSpec]:
    """Ordered layer list for takt evaluate / run requests."""
    by_scope = profile_to_layer_specs(profile)
    return [by_scope[scope] for scope in profile.review_pipeline]


def scope_to_layer_index(profile: ReviewProfile) -> dict[ReviewScope, int]:
    return {scope: idx for idx, scope in enumerate(profile.review_pipeline)}


# Backward-compatible names used in docs / older call sites
def profile_to_homeostats(profile: ReviewProfile) -> dict[ReviewScope, LayerSpec]:
    return profile_to_layer_specs(profile)


def build_layered_homeostats(profile: ReviewProfile) -> list[tuple[int, LayerSpec]]:
    return [(spec.layer, spec) for spec in build_layer_specs(profile)]


__all__ = [
    "build_layer_specs",
    "build_layered_homeostats",
    "profile_to_homeostats",
    "profile_to_layer_specs",
    "scope_to_layer_index",
]

"""Map ReviewProfile to takt 0.1.1 ProfilHomeostatyczny.

Each review scope becomes one layer in the cascade.
We derive EssentialVariables and thresholds from the profile's action policy,
review dimensions, and conservative defaults for strict fail-closed behavior.
"""

from __future__ import annotations

from typing import Any

from takt import EssentialVariable, ProfilHomeostatyczny

from reviewkit.profile import ActionPolicyConfig, ReviewProfile, ReviewScope


def _severity_to_deviation(severity: str) -> float:
    mapping = {
        "info": 0.1,
        "low": 0.3,
        "medium": 0.6,
        "high": 0.85,
        "critical": 1.0,
    }
    return mapping.get(severity.lower(), 0.6)


def profile_to_homeostats(profile: ReviewProfile) -> dict[ReviewScope, ProfilHomeostatyczny]:
    """Return one ProfilHomeostatyczny per enabled scope in review order.

    Layer numbering: 0 for the first (lowest) scope in pipeline, increasing upwards.
    """
    policy = profile.resolved_action_policy()
    pipeline = profile.review_pipeline

    homeostats: dict[ReviewScope, ProfilHomeostatyczny] = {}

    for idx, scope in enumerate(pipeline):
        h = ProfilHomeostatyczny(layer=idx)

        # Core variable: aberration derived from severity/confidence of findings
        # We treat "presence of medium+ issue" as a critical variable.
        h.add_variable(
            EssentialVariable(
                name="aberration",
                tolerance=0.5,  # below this we usually do nothing
                cutoff=0.05,
            )
        )

        # Map policy min_confidence
        h.min_confidence = max(0.1, float(policy.min_confidence_for_auto_apply or 0.6))

        # Entropy threshold: be strict. High residual means human or conflict.
        h.entropy_threshold = 0.30

        # Add per-dimension variables if present (future extension point)
        for dim in profile.review_dimensions:
            dim_id = dim.id if hasattr(dim, "id") else str(dim)
            h.add_variable(
                EssentialVariable(
                    name=f"dim.{dim_id}",
                    tolerance=0.4,
                    cutoff=0.1,
                )
            )

        # From apply_policy we can tighten further
        if policy.max_severity_for_auto_apply:
            # If max severity for auto is low, tighten aberration tolerance
            if policy.max_severity_for_auto_apply in ("low", "info"):
                h.variables["aberration"].tolerance = 0.25

        homeostats[scope] = h

    return homeostats


def build_layered_homeostats(
    profile: ReviewProfile,
) -> list[tuple[int, ProfilHomeostatyczny]]:
    """Return list suitable for takt.build_cascade: [(layer, homeostat), ...]"""
    hs = profile_to_homeostats(profile)
    ordered = []
    for layer, scope in enumerate(profile.review_pipeline):
        ordered.append((layer, hs[scope]))
    return ordered


__all__ = ["profile_to_homeostats", "build_layered_homeostats"]

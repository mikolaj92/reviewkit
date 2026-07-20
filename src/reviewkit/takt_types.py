"""Host-side types for the takt 0.2.0 (Mojo-only) JSON boundary.

Takt no longer ships a Python runtime. ReviewKit owns detectors and plant
construction; takt receives plant_nodes + layers + raw_signals and returns
actuation / interlock / stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Outcome = Literal["actuation", "interlock", "stable"]


@dataclass(frozen=True)
class RawSignal:
    """Raw detector signal before fusion (matches takt RawSignal JSON)."""

    signal_id: str
    node_id: str
    detector: str
    deviation: float
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "node_id": self.node_id,
            "detector": self.detector,
            "deviation": float(self.deviation),
            "confidence": float(self.confidence),
        }


@dataclass(frozen=True)
class LayerSpec:
    """One cascade layer homeostat config (matches takt layers[] JSON)."""

    layer: int
    tolerance: float = 0.5
    cutoff: float = 0.05
    min_confidence: float = 0.6
    entropy_threshold: float = 0.30

    def to_json(self) -> dict[str, Any]:
        return {
            "layer": int(self.layer),
            "tolerance": float(self.tolerance),
            "cutoff": float(self.cutoff),
            "min_confidence": float(self.min_confidence),
            "entropy_threshold": float(self.entropy_threshold),
        }


@dataclass(frozen=True)
class PlantNode:
    """Numeric plant node for the Mojo step (host maps domain → plant)."""

    id: str
    value: float = 0.0
    has_children: bool = False
    parent_id: str = ""
    layer: int = 0
    kind: str = "node"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "value": float(self.value),
            "has_children": bool(self.has_children),
            "parent_id": self.parent_id or "",
            "layer": int(self.layer),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class ErrorSignalView:
    aberration: float = 0.0
    confidence: float = 1.0
    residual_entropy: float = 0.0
    reducer: str = "none"


@dataclass(frozen=True)
class ActuationView:
    node_id: str
    command: str = "correct_aberration"


@dataclass(frozen=True)
class InterlockView:
    reason: str
    residual_entropy: float = 0.0


@dataclass(frozen=True)
class TaktDecision:
    """Thin decision envelope from takt evaluate (Mojo or local fallback)."""

    outcome: Outcome
    node_id: str
    error: ErrorSignalView | None = None
    actuation: ActuationView | None = None
    interlock: InterlockView | None = None
    telemetry_count: int = 0
    engine: str = "local"

    @property
    def has_interlock(self) -> bool:
        return self.outcome == "interlock" or self.interlock is not None

    @property
    def has_actuation(self) -> bool:
        return self.outcome == "actuation" or self.actuation is not None


__all__ = [
    "ActuationView",
    "ErrorSignalView",
    "InterlockView",
    "LayerSpec",
    "Outcome",
    "PlantNode",
    "RawSignal",
    "TaktDecision",
]

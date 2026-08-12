"""Client for the canonical in-process Takt Mojo cascade binding."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from reviewkit.takt_types import (
    ActuationView,
    ErrorSignalView,
    InterlockView,
    LayerSpec,
    PlantNode,
    RawSignal,
    TaktDecision,
)


def _parse_mojo_result(payload: dict[str, Any]) -> TaktDecision:
    if not payload.get("ok", True) and payload.get("error"):
        raise RuntimeError(f"takt mojo step failed: {payload.get('error')}")

    outcome = payload.get("outcome")
    if outcome not in ("actuation", "interlock", "stable"):
        raise ValueError(f"invalid takt outcome: {outcome!r}")

    node_id = str(payload.get("node_id") or "")
    sig = payload.get("signals") or {}
    err = None
    if isinstance(sig.get("error"), dict):
        e = sig["error"]
        err = ErrorSignalView(
            aberration=float(e.get("aberration", 0.0)),
            confidence=float(e.get("confidence", 1.0)),
            residual_entropy=float(e.get("residual_entropy", 0.0)),
            reducer=str(e.get("reducer", "none")),
        )
    actuation = None
    if isinstance(sig.get("actuation"), dict):
        a = sig["actuation"]
        actuation = ActuationView(
            node_id=str(a.get("node_id") or node_id),
            command=str(a.get("command") or "correct_aberration"),
        )
    interlock = None
    if isinstance(sig.get("interlock"), dict):
        il = sig["interlock"]
        interlock = InterlockView(
            reason=str(il.get("reason") or "takt interlock"),
            residual_entropy=float(il.get("residual_entropy", 0.0)),
        )

    return TaktDecision(
        outcome=outcome,  # type: ignore[arg-type]
        node_id=node_id,
        error=err,
        actuation=actuation,
        interlock=interlock,
        telemetry_count=int(sig.get("telemetry_count") or 0),
    )


def _evaluate_request(
    *,
    plant_nodes: Sequence[PlantNode],
    layers: Sequence[LayerSpec],
    raw_signals: Sequence[RawSignal],
    now: str | None = None,
) -> dict[str, Any]:
    return {
        "mode": "evaluate",
        "now": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plant_nodes": [n.to_json() for n in plant_nodes],
        "layers": [L.to_json() for L in layers],
        "raw_signals": [s.to_json() for s in raw_signals],
    }


def evaluate_binding(
    *,
    plant_nodes: Sequence[PlantNode],
    layers: Sequence[LayerSpec],
    raw_signals: Sequence[RawSignal],
    now: str | None = None,
) -> TaktDecision:
    """In-process Mojo via the official ``takt`` Python package (cascade_step)."""
    try:
        import takt as takt_pkg
    except ImportError as exc:
        raise ImportError(
            "takt Python package not installed; install the pinned dependency"
        ) from exc

    request = _evaluate_request(
        plant_nodes=plant_nodes,
        layers=layers,
        raw_signals=raw_signals,
        now=now,
    )
    payload = takt_pkg.cascade_step(request)
    return _parse_mojo_result(payload)


class TaktClient:
    """Evaluate one tact through the official in-process Takt binding."""

    def evaluate(
        self,
        *,
        plant_nodes: Sequence[PlantNode],
        layers: Sequence[LayerSpec],
        raw_signals: Sequence[RawSignal] = (),
    ) -> TaktDecision:
        return evaluate_binding(
            plant_nodes=plant_nodes,
            layers=layers,
            raw_signals=raw_signals,
        )


__all__ = ["TaktClient", "evaluate_binding"]

"""Client for takt Mojo cascade: Python binding, subprocess, or local fallback.

Order (``REVIEWKIT_TAKT_ENGINE``):
  - ``auto`` (default): in-process ``import takt`` binding → local fallback
  - ``binding`` / ``python``: force thin Python package (takt >= 0.3)
  - ``mojo`` / ``subprocess``: ``tools/takt_step.sh`` under ``TAKT_HOME``
  - ``local``: pure-Python fusion/homeostat (tests / no Mojo toolchain)

No dual engine: binding and subprocess call the same Mojo cascade; local is a
compatibility mirror only.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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


def _default_takt_homes() -> list[Path]:
    candidates: list[Path] = []
    env = os.environ.get("TAKT_HOME")
    if env:
        candidates.append(Path(env).expanduser())
    # Sibling of reviewkit when developed in ~/Developer/OSS/*
    here = Path(__file__).resolve()
    for parent in here.parents:
        sibling = parent / "takt"
        if sibling.is_dir():
            candidates.append(sibling)
        # stop at OSS-ish depth; avoid walking to /
        if parent.name in {"OSS", "Developer", "src"} or parent == Path.home():
            break
    # Common local layout
    candidates.append(Path.home() / "Developer" / "OSS" / "takt")
    return candidates


def resolve_takt_home() -> Path | None:
    """Return first takt checkout that has tools/takt_step.sh, or None."""
    for home in _default_takt_homes():
        step = home / "tools" / "takt_step.sh"
        if step.is_file():
            return home
    return None


@dataclass
class _FusedError:
    aberration: float
    confidence: float
    residual_entropy: float
    reducer: str


def fuse_raw_signals(raw_signals: Sequence[RawSignal], node_id: str) -> _FusedError:
    """Local fusion matching mojo/takt/fusion.mojo (0.2.0)."""
    del node_id  # used only for ErrorSignal id in Mojo
    if not raw_signals:
        return _FusedError(0.0, 1.0, 0.0, "empty")

    n = len(raw_signals)
    weighted_sum = sum(s.deviation for s in raw_signals)
    aberration = weighted_sum / float(n)
    min_conf = min(s.confidence for s in raw_signals)

    variance = sum((s.deviation - aberration) ** 2 for s in raw_signals) / float(n)
    spread = math.sqrt(variance)
    scale = abs(aberration) + 1.0
    disagree = min(1.0, spread / scale)

    saw_pos = any(s.deviation > 1e-9 for s in raw_signals)
    saw_neg = any(s.deviation < -1e-9 for s in raw_signals)
    conflict = saw_pos and saw_neg

    confidence = min_conf
    if conflict:
        confidence = min(min_conf * 0.25, 0.15)
    elif disagree > 0.25:
        confidence = min_conf * (1.0 - 0.5 * disagree)

    residual = max(0.3, 1.0 - confidence, disagree)
    if conflict:
        residual = max(residual, 0.85)

    reducer = "fallback"
    if conflict:
        reducer = "fallback_conflict"
    elif disagree > 0.25:
        reducer = "fallback_disagreement"

    return _FusedError(aberration, confidence, residual, reducer)


def decide_from_error(error: _FusedError, layer: LayerSpec, node_id: str) -> TaktDecision:
    """Homeostat decision matching mojo/takt/regulator.mojo + homeostat.mojo."""
    err_view = ErrorSignalView(
        aberration=error.aberration,
        confidence=error.confidence,
        residual_entropy=error.residual_entropy,
        reducer=error.reducer,
    )

    if (
        error.residual_entropy > layer.entropy_threshold
        or error.confidence < layer.min_confidence
    ):
        return TaktDecision(
            outcome="interlock",
            node_id=node_id,
            error=err_view,
            interlock=InterlockView(
                reason="high_residual_entropy_or_low_confidence",
                residual_entropy=error.residual_entropy,
            ),
            engine="local",
        )

    # Single essential variable "dev" with layer.tolerance (Mojo adapter shape).
    should_act = abs(error.aberration) > layer.tolerance
    if should_act:
        return TaktDecision(
            outcome="actuation",
            node_id=node_id,
            error=err_view,
            actuation=ActuationView(node_id=node_id),
            engine="local",
        )

    return TaktDecision(
        outcome="stable",
        node_id=node_id,
        error=err_view,
        engine="local",
    )


def evaluate_local(
    *,
    plant_nodes: Sequence[PlantNode],
    layers: Sequence[LayerSpec],
    raw_signals: Sequence[RawSignal],
) -> TaktDecision:
    """One-tact evaluate without Mojo (mirrors cascade_step mode=evaluate)."""
    if not plant_nodes:
        raise ValueError("plant_nodes must not be empty")
    if not layers:
        raise ValueError("layers must not be empty")

    node = plant_nodes[0]
    # Prefer layer matching node.layer; else lowest layer.
    layer = next((L for L in layers if L.layer == node.layer), layers[0])

    # Intrinsic node value as deviation (same as CascadeRegulator).
    signals = list(raw_signals)
    if abs(node.value) > 1e-12:
        signals.append(
            RawSignal(
                signal_id=f"node_value:{node.id}",
                node_id=node.id,
                detector="intrinsic_value",
                deviation=node.value,
                confidence=0.8,
            )
        )

    fused = fuse_raw_signals(signals, node.id)
    return decide_from_error(fused, layer, node.id)


def _parse_mojo_result(payload: dict[str, Any], *, engine: str = "mojo") -> TaktDecision:
    if not payload.get("ok", True) and payload.get("error"):
        raise RuntimeError(f"takt mojo step failed: {payload.get('error')}")

    outcome = str(payload.get("outcome") or "stable")
    if outcome not in ("actuation", "interlock", "stable"):
        # Infer from signals when outcome missing
        sig = payload.get("signals") or {}
        if sig.get("interlock"):
            outcome = "interlock"
        elif sig.get("actuation"):
            outcome = "actuation"
        else:
            outcome = "stable"

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
        engine=engine,
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
            "takt Python package not installed; pin takt@v0.3+ or use local/subprocess"
        ) from exc

    # Prefer checkout when present so the binding can JIT-compile Mojo sources.
    home = resolve_takt_home()
    if home is not None:
        os.environ.setdefault("TAKT_HOME", str(home))

    request = _evaluate_request(
        plant_nodes=plant_nodes,
        layers=layers,
        raw_signals=raw_signals,
        now=now,
    )
    payload = takt_pkg.cascade_step(request)
    return _parse_mojo_result(payload, engine="binding")


def evaluate_mojo(
    *,
    plant_nodes: Sequence[PlantNode],
    layers: Sequence[LayerSpec],
    raw_signals: Sequence[RawSignal],
    takt_home: Path | None = None,
    now: str | None = None,
) -> TaktDecision:
    """Call tools/takt_step.sh with a temporary request JSON."""
    home = takt_home or resolve_takt_home()
    if home is None:
        raise FileNotFoundError(
            "TAKT_HOME not set and no sibling takt checkout with tools/takt_step.sh"
        )
    step = home / "tools" / "takt_step.sh"
    if not step.is_file():
        raise FileNotFoundError(f"missing {step}")

    request = _evaluate_request(
        plant_nodes=plant_nodes,
        layers=layers,
        raw_signals=raw_signals,
        now=now,
    )

    with tempfile.TemporaryDirectory(prefix="reviewkit-takt-") as tmp:
        req_path = Path(tmp) / "request.json"
        req_path.write_text(json.dumps(request), encoding="utf-8")
        env = os.environ.copy()
        env["TAKT_REQUEST_PATH"] = str(req_path)
        env.setdefault("TAKT_HOME", str(home))
        proc = subprocess.run(
            ["bash", str(step)],
            cwd=str(home),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"takt_step.sh exited {proc.returncode}: {err or 'no output'}"
            )
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            raise RuntimeError("takt_step.sh produced empty stdout")
        payload = json.loads(line[-1])
        return _parse_mojo_result(payload)


def _resolve_engine(prefer_mojo: bool | None) -> str:
    if prefer_mojo is True:
        return "mojo"
    if prefer_mojo is False:
        return "local"
    raw = os.environ.get("REVIEWKIT_TAKT_ENGINE", "auto").strip().lower()
    if raw in {"", "auto", "default"}:
        return "auto"
    if raw in {"binding", "python", "py"}:
        return "binding"
    if raw in {"mojo", "subprocess", "shell"}:
        return "mojo"
    if raw in {"local", "fallback"}:
        return "local"
    return "auto"


class TaktClient:
    """Evaluate one tact via binding / subprocess / local fallback."""

    def __init__(
        self,
        *,
        prefer_mojo: bool | None = None,
        takt_home: Path | None = None,
        engine: str | None = None,
    ) -> None:
        self.takt_home = takt_home or resolve_takt_home()
        self.engine = engine or _resolve_engine(prefer_mojo)
        # Back-compat flag used by older call sites / tests.
        self.prefer_mojo = self.engine == "mojo"

    def evaluate(
        self,
        *,
        plant_nodes: Sequence[PlantNode],
        layers: Sequence[LayerSpec],
        raw_signals: Sequence[RawSignal] = (),
    ) -> TaktDecision:
        engine = self.engine
        if engine == "binding":
            return evaluate_binding(
                plant_nodes=plant_nodes,
                layers=layers,
                raw_signals=raw_signals,
            )
        if engine == "mojo":
            return evaluate_mojo(
                plant_nodes=plant_nodes,
                layers=layers,
                raw_signals=raw_signals,
                takt_home=self.takt_home,
            )
        if engine == "local":
            return evaluate_local(
                plant_nodes=plant_nodes,
                layers=layers,
                raw_signals=raw_signals,
            )
        # auto: binding when available, else local
        try:
            return evaluate_binding(
                plant_nodes=plant_nodes,
                layers=layers,
                raw_signals=raw_signals,
            )
        except Exception:
            return evaluate_local(
                plant_nodes=plant_nodes,
                layers=layers,
                raw_signals=raw_signals,
            )


__all__ = [
    "TaktClient",
    "decide_from_error",
    "evaluate_binding",
    "evaluate_local",
    "evaluate_mojo",
    "fuse_raw_signals",
    "resolve_takt_home",
]

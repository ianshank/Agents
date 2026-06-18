"""Versioned persistence for run state and fitted calibrators.

run-state schema version (RUN_STATE_SCHEMA_VERSION) is intentionally separate
from config SCHEMA_VERSION: the on-disk format of run results may evolve on a
different cadence from the config schema. version.py is NOT modified here.

On-disk contract (fixed, not configurable):
  json.dumps(..., sort_keys=True, separators=(",", ":"))  — compact, deterministic
All loaded values are explicitly cast to their target types; no implicit Any flow.
Unknown keys in a payload raise ValueError (strict, like config.from_dict).

Note on ``allowance`` serialization: ``CycleState.allowance`` defaults to
``float("inf")`` but standard JSON cannot represent infinity.  We serialize
inf allowance as JSON ``null`` and restore it as ``float("inf")`` on load.
Real controllers always set a finite allowance before running cycles.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from typing import Any

from .calibration import Calibrator, IsotonicCalibrator
from .config import RecalibrationConfig
from .loop import RunResult
from .protocols import CycleState, StopReason
from .recalibration import TemperatureScaler

RUN_STATE_SCHEMA_VERSION = "1.0.0"

# --- internal migration infrastructure ---------------------------------------
_RunStateDict = dict[str, Any]
_MigrationFn = Callable[[_RunStateDict], _RunStateDict]


def _migrate_run_0_9_0_to_1_0_0(data: _RunStateDict) -> _RunStateDict:
    """Stub: 0.9.0 (pre-release) payloads had no schema_version field."""
    data = dict(data)
    data["schema_version"] = "1.0.0"
    return data


_RUN_STATE_MIGRATIONS: dict[str, _MigrationFn] = {
    "0.9.0": _migrate_run_0_9_0_to_1_0_0,
}


def _migrate_run_state(data: _RunStateDict) -> _RunStateDict:
    """Bring a run-state dict up to RUN_STATE_SCHEMA_VERSION."""
    data = dict(data)
    version = str(data.get("schema_version", RUN_STATE_SCHEMA_VERSION))
    seen: set[str] = set()
    while version != RUN_STATE_SCHEMA_VERSION:
        if version in seen:  # pragma: no cover  # cycle guard; unreachable via valid migrations
            raise ValueError(f"run-state migration cycle at {version!r}")
        seen.add(version)
        migration = _RUN_STATE_MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"no run-state migration path from {version!r} to {RUN_STATE_SCHEMA_VERSION!r}"
            )
        data = migration(data)
        version = str(data.get("schema_version", RUN_STATE_SCHEMA_VERSION))
    return data


# --- CycleState serialization -------------------------------------------------


def cycle_state_to_dict(state: CycleState) -> dict[str, Any]:
    """Serialize CycleState to a JSON-safe dict.

    ``allowance`` is serialized as ``null`` when infinite (JSON cannot
    represent infinity); ``cycle_state_from_dict`` restores it as
    ``float("inf")``.
    """
    return {
        "cycle_index": int(state.cycle_index),
        "unresolved": list(state.unresolved),
        "last_max_conf_delta": (
            float(state.last_max_conf_delta) if state.last_max_conf_delta is not None else None
        ),
        "allowance": float(state.allowance) if not math.isinf(state.allowance) else None,
    }


_CYCLE_STATE_KEYS = frozenset({"cycle_index", "unresolved", "last_max_conf_delta", "allowance"})


def cycle_state_from_dict(d: dict[str, Any]) -> CycleState:
    """Deserialize CycleState; rejects unknown keys."""
    unknown = set(d) - _CYCLE_STATE_KEYS
    if unknown:
        raise ValueError(f"unknown cycle_state keys: {sorted(unknown)}")
    delta_raw = d.get("last_max_conf_delta")
    delta: float | None = float(delta_raw) if delta_raw is not None else None
    allowance_raw = d.get("allowance")
    allowance = float("inf") if allowance_raw is None else float(allowance_raw)
    return CycleState(
        cycle_index=int(d["cycle_index"]),
        unresolved=tuple(str(c) for c in d["unresolved"]),
        last_max_conf_delta=delta,
        allowance=allowance,
    )


# --- RunResult serialization -------------------------------------------------


def run_result_to_dict(result: RunResult) -> dict[str, Any]:
    """Serialize RunResult to a JSON-safe dict, stamped with schema_version."""
    return {
        "schema_version": RUN_STATE_SCHEMA_VERSION,
        "reason": str(result.reason.value),
        "partial": bool(result.partial),
        "cycles_completed": int(result.cycles_completed),
        "spent": float(result.spent),
        "reserve_available": float(result.reserve_available),
        "detail": str(result.detail),
        "overspent": bool(result.overspent),
        "final_state": cycle_state_to_dict(result.final_state),
    }


_RUN_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "reason",
        "partial",
        "cycles_completed",
        "spent",
        "reserve_available",
        "detail",
        "overspent",
        "final_state",
    }
)


def run_result_from_dict(d: dict[str, Any]) -> RunResult:
    """Deserialize RunResult; migrates old schema versions; rejects unknown keys."""
    d = _migrate_run_state(dict(d))
    unknown = set(d) - _RUN_RESULT_KEYS
    if unknown:
        raise ValueError(f"unknown run_result keys: {sorted(unknown)}")
    return RunResult(
        reason=StopReason(str(d["reason"])),
        partial=bool(d["partial"]),
        cycles_completed=int(d["cycles_completed"]),
        spent=float(d["spent"]),
        reserve_available=float(d["reserve_available"]),
        detail=str(d.get("detail", "")),
        overspent=bool(d.get("overspent", False)),
        final_state=cycle_state_from_dict(d["final_state"]),
    )


# --- Calibrator serialization ------------------------------------------------


def calibrator_to_dict(cal: Calibrator) -> dict[str, Any]:
    """Serialize a fitted calibrator.  Stores all params predict() needs.

    The restored calibrator predicts WITHOUT requiring a live config object.
    """
    if isinstance(cal, IsotonicCalibrator):
        if not cal._fitted:
            raise ValueError("IsotonicCalibrator is not fitted; cannot serialize")
        return {
            "type": "isotonic",
            "params": {
                "x": list(cal._x),
                "y": list(cal._y),
            },
        }
    if isinstance(cal, TemperatureScaler):
        if cal._T is None:
            raise ValueError("TemperatureScaler is not fitted; cannot serialize")
        return {
            "type": "temperature",
            "params": {
                "T": float(cal._T),
                "clamp_eps": float(cal._config.clamp_eps),
            },
        }
    raise TypeError(f"unsupported calibrator type: {type(cal).__name__!r}")


_CALIBRATOR_OUTER_KEYS = frozenset({"type", "params"})
_ISOTONIC_PARAM_KEYS = frozenset({"x", "y"})
_TEMPERATURE_PARAM_KEYS = frozenset({"T", "clamp_eps"})


def calibrator_from_dict(d: dict[str, Any]) -> Calibrator:
    """Deserialize a calibrator.  Self-contained: needs no live config."""
    unknown_outer = set(d) - _CALIBRATOR_OUTER_KEYS
    if unknown_outer:
        raise ValueError(f"unknown calibrator keys: {sorted(unknown_outer)}")
    cal_type = str(d["type"])
    params: dict[str, Any] = dict(d["params"])

    if cal_type == "isotonic":
        unknown_params = set(params) - _ISOTONIC_PARAM_KEYS
        if unknown_params:
            raise ValueError(f"unknown isotonic params: {sorted(unknown_params)}")
        cal = IsotonicCalibrator()
        cal._x = [float(v) for v in params["x"]]
        cal._y = [float(v) for v in params["y"]]
        cal._fitted = True
        return cal

    if cal_type == "temperature":
        unknown_params = set(params) - _TEMPERATURE_PARAM_KEYS
        if unknown_params:
            raise ValueError(f"unknown temperature params: {sorted(unknown_params)}")
        cfg = RecalibrationConfig(clamp_eps=float(params["clamp_eps"]))
        scaler = TemperatureScaler(cfg)
        scaler._T = float(params["T"])
        return scaler

    raise ValueError(f"unknown calibrator type: {cal_type!r}")


# --- File I/O ----------------------------------------------------------------


def save_run(result: RunResult, path: str) -> None:
    """Write RunResult to a JSON file.  Atomic: writes to temp then renames."""
    d = run_result_to_dict(result)
    serialized = json.dumps(d, sort_keys=True, separators=(",", ":"))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(serialized)
    os.replace(tmp, path)


def load_run(path: str) -> RunResult:
    """Load RunResult from a JSON file, migrating older schema versions."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return run_result_from_dict(d)

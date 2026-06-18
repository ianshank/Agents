"""Tests for persistence — structural + BEHAVIOURAL round-trips."""

from __future__ import annotations

import json
import math
import os
import tempfile

import hypothesis.strategies as st
import pytest
from hypothesis import given

from agent_core import (
    CycleState,
    IsotonicCalibrator,
    RunResult,
    StopReason,
)
from agent_core.config import RecalibrationConfig
from agent_core.persistence import (
    RUN_STATE_SCHEMA_VERSION,
    calibrator_from_dict,
    calibrator_to_dict,
    cycle_state_from_dict,
    cycle_state_to_dict,
    load_run,
    run_result_from_dict,
    run_result_to_dict,
    save_run,
)
from agent_core.recalibration import TemperatureScaler

# ---- helpers ----------------------------------------------------------------


def _make_run_result(
    reason: StopReason = StopReason.SUCCESS,
    cycles: int = 3,
    spent: float = 9.0,
) -> RunResult:
    return RunResult(
        reason=reason,
        partial=False,
        cycles_completed=cycles,
        spent=spent,
        reserve_available=90000.0,
        final_state=CycleState(cycle_index=cycles + 1, unresolved=(), last_max_conf_delta=0.01),
        detail="converged",
        overspent=False,
    )


def _fitted_isotonic(n: int = 20) -> IsotonicCalibrator:
    probs = [i / n for i in range(1, n + 1)]
    labels = [1 if i % 2 == 0 else 0 for i in range(1, n + 1)]
    cal = IsotonicCalibrator()
    cal.fit(probs, labels)
    return cal


def _fitted_temperature(n: int = 100) -> TemperatureScaler:
    probs = [0.9] * (n // 2) + [0.1] * (n // 2)
    labels = [1] * (n // 2) + [0] * (n // 2)
    cfg = RecalibrationConfig()
    cal = TemperatureScaler(cfg)
    cal.fit(probs, labels)
    return cal


# ---- CycleState round-trip --------------------------------------------------


def test_cycle_state_structural_round_trip() -> None:
    state = CycleState(cycle_index=4, unresolved=("c1", "c2"), last_max_conf_delta=0.03)
    restored = cycle_state_from_dict(cycle_state_to_dict(state))
    assert restored == state


def test_cycle_state_null_delta() -> None:
    state = CycleState(last_max_conf_delta=None)
    restored = cycle_state_from_dict(cycle_state_to_dict(state))
    assert restored.last_max_conf_delta is None


def test_cycle_state_inf_allowance() -> None:
    state = CycleState(allowance=float("inf"))
    d = cycle_state_to_dict(state)
    # inf allowance is serialized as None (JSON null) so it can round-trip through JSON
    assert d["allowance"] is None
    # from_dict should also handle None → inf
    restored = cycle_state_from_dict(d)
    assert math.isinf(restored.allowance)


def test_cycle_state_finite_allowance_round_trips() -> None:
    state = CycleState(allowance=1234.5)
    restored = cycle_state_from_dict(cycle_state_to_dict(state))
    assert restored.allowance == 1234.5


def test_cycle_state_unknown_key_raises() -> None:
    d = cycle_state_to_dict(CycleState())
    d["extra"] = "bad"
    with pytest.raises(ValueError, match="unknown cycle_state keys"):
        cycle_state_from_dict(d)


# ---- RunResult round-trip ---------------------------------------------------


def test_run_result_structural_round_trip() -> None:
    for reason in (StopReason.SUCCESS, StopReason.STALL, StopReason.BUDGET, StopReason.CAP):
        result = _make_run_result(reason)
        d = run_result_to_dict(result)
        assert d["schema_version"] == RUN_STATE_SCHEMA_VERSION
        restored = run_result_from_dict(d)
        assert restored == result


def test_run_result_schema_version_present() -> None:
    d = run_result_to_dict(_make_run_result())
    assert "schema_version" in d
    assert d["schema_version"] == RUN_STATE_SCHEMA_VERSION


def test_run_result_unknown_key_raises() -> None:
    d = run_result_to_dict(_make_run_result())
    d["surprise"] = 42
    with pytest.raises(ValueError, match="unknown run_result keys"):
        run_result_from_dict(d)


def test_run_result_invalid_reason_raises() -> None:
    d = run_result_to_dict(_make_run_result())
    d["reason"] = "not_a_valid_reason"
    with pytest.raises(ValueError):
        run_result_from_dict(d)


# ---- Migration: 0.9.0 → 1.0.0 ----------------------------------------------


def test_run_result_migrates_from_0_9_0() -> None:
    """A 0.9.0 payload (no schema_version field) migrates to 1.0.0."""
    result = _make_run_result()
    d = run_result_to_dict(result)
    # Simulate a real 0.9.0 payload: the field was ABSENT (not "0.9.0")
    del d["schema_version"]
    restored = run_result_from_dict(d)
    assert restored == result


def test_migration_unknown_version_raises() -> None:
    """A payload with an unknown version that has no migration path raises ValueError."""
    d = run_result_to_dict(_make_run_result())
    d["schema_version"] = "99.99.99"
    with pytest.raises(ValueError, match="no run-state migration path"):
        run_result_from_dict(d)


# ---- Calibrator round-trip: BEHAVIOURAL (predict values, not just params) ---


def test_isotonic_behavioural_round_trip() -> None:
    """Restored IsotonicCalibrator must produce identical predictions to original."""
    original = _fitted_isotonic(30)
    grid = [i / 100.0 for i in range(1, 100)]
    d = calibrator_to_dict(original)
    restored = calibrator_from_dict(d)
    for p in grid:
        orig_pred = original.predict(p)
        rest_pred = restored.predict(p)
        assert math.isclose(orig_pred, rest_pred, abs_tol=1e-12), (
            f"IsotonicCalibrator predict({p}) differs: {orig_pred} vs {rest_pred}"
        )


def test_temperature_behavioural_round_trip() -> None:
    """Restored TemperatureScaler must produce identical predictions to original."""
    original = _fitted_temperature(100)
    grid = [i / 100.0 for i in range(1, 100)]
    d = calibrator_to_dict(original)
    restored = calibrator_from_dict(d)
    for p in grid:
        orig_pred = original.predict(p)
        rest_pred = restored.predict(p)
        assert math.isclose(orig_pred, rest_pred, abs_tol=1e-12), (
            f"TemperatureScaler predict({p}) differs: {orig_pred} vs {rest_pred}"
        )


def test_calibrator_dict_has_type_tag() -> None:
    d = calibrator_to_dict(_fitted_isotonic())
    assert d["type"] == "isotonic"
    assert "params" in d


def test_calibrator_temperature_stores_t_and_eps() -> None:
    d = calibrator_to_dict(_fitted_temperature())
    assert d["type"] == "temperature"
    assert "T" in d["params"]
    assert "clamp_eps" in d["params"]


def test_unfitted_isotonic_raises() -> None:
    with pytest.raises(ValueError, match="not fitted"):
        calibrator_to_dict(IsotonicCalibrator())


def test_unfitted_temperature_raises() -> None:
    with pytest.raises(ValueError, match="not fitted"):
        calibrator_to_dict(TemperatureScaler(RecalibrationConfig()))


def test_calibrator_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown calibrator type"):
        calibrator_from_dict({"type": "mystery", "params": {}})


def test_calibrator_unknown_outer_key_raises() -> None:
    d = calibrator_to_dict(_fitted_isotonic())
    d["extra"] = "bad"
    with pytest.raises(ValueError, match="unknown calibrator keys"):
        calibrator_from_dict(d)


def test_calibrator_unknown_params_key_raises() -> None:
    d = calibrator_to_dict(_fitted_isotonic())
    d["params"]["bonus"] = 99
    with pytest.raises(ValueError, match="unknown isotonic params"):
        calibrator_from_dict(d)


def test_calibrator_unknown_temperature_params_key_raises() -> None:
    d = calibrator_to_dict(_fitted_temperature())
    d["params"]["bonus"] = 99
    with pytest.raises(ValueError, match="unknown temperature params"):
        calibrator_from_dict(d)


def test_unsupported_calibrator_type_raises() -> None:
    """A Protocol-compliant but unknown calibrator class raises TypeError."""

    class Dummy:
        def fit(self, probs, outcomes):  # type: ignore[no-untyped-def]
            return self

        def predict(self, prob: float) -> float:
            return prob

    dummy = Dummy()
    with pytest.raises(TypeError, match="unsupported calibrator type"):
        calibrator_to_dict(dummy)  # type: ignore[arg-type]


# ---- Hypothesis round-trip --------------------------------------------------


@given(
    cycles=st.integers(min_value=1, max_value=20),
    spent=st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)
def test_run_result_hypothesis_round_trip(cycles: int, spent: float) -> None:
    result = _make_run_result(StopReason.SUCCESS, cycles, spent)
    restored = run_result_from_dict(run_result_to_dict(result))
    assert restored == result


# ---- File I/O ----------------------------------------------------------------


def test_save_and_load_run() -> None:
    result = _make_run_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "run.json")
        save_run(result, path)
        loaded = load_run(path)
    assert loaded == result


def test_save_produces_valid_json() -> None:
    result = _make_run_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "run.json")
        save_run(result, path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        parsed = json.loads(content)
    assert "schema_version" in parsed
    assert parsed["reason"] == "success"


def test_save_is_deterministic() -> None:
    """save_run with the same RunResult must produce byte-for-byte identical files."""
    result = _make_run_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        p1 = os.path.join(tmpdir, "r1.json")
        p2 = os.path.join(tmpdir, "r2.json")
        save_run(result, p1)
        save_run(result, p2)
        with open(p1, encoding="utf-8") as f:
            c1 = f.read()
        with open(p2, encoding="utf-8") as f:
            c2 = f.read()
    assert c1 == c2


def test_save_run_cleans_up_tmp_on_failure() -> None:
    """save_run removes the .tmp file when the write fails mid-way."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write to a path whose parent directory does not exist; open() raises OSError.
        path = os.path.join(tmpdir, "missing_subdir", "run.json")
        with pytest.raises(OSError):
            save_run(_make_run_result(), path)
        # The .tmp was never created, so suppressed unlink is a no-op.
        assert not os.path.exists(path + ".tmp")


def test_save_is_compact_no_whitespace() -> None:
    """The saved JSON uses compact separators (no spaces after : or ,)."""
    result = _make_run_result()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "run.json")
        save_run(result, path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
    # compact format: no ": " or ", " sequences
    assert ": " not in content
    assert ", " not in content

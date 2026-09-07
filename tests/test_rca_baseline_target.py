#!/usr/bin/env python3
"""Tests for the max-|Z| baseline target (add-rca-eval-matrix task 3).

The baseline is a target, not a scorer: it produces a diagnosis and is graded by the
same scorers as any agent. These tests pin its determinism contract (spec: "no clock,
no random source, no network") and its abstention behaviour.
"""

from __future__ import annotations

import pytest

from eval_harness.core.types import EvalItem
from eval_harness.plugins import TARGETS, bootstrap

bootstrap()


def _telemetry(spike: dict[str, float]) -> dict:
    """Two candidates' metrics; svc-a spikes by ``spike['svc-a']`` at the onset."""
    metrics: dict[str, dict] = {}
    for svc in ("svc-a", "svc-b"):
        step = spike.get(svc, 0.0)
        metrics[svc] = {
            "latency_ms": {
                "pre": [100.0, 101.0, 99.0, 100.5],
                "post": [100.0 + step, 101.0 + step, 99.0 + step, 100.5 + step],
            }
        }
    return {"metrics": metrics, "events": []}


def _item() -> EvalItem:
    return EvalItem(
        id="rca-t",
        inputs={"candidates": ["svc-a", "svc-b"], "telemetry": _telemetry({"svc-a": 400.0})},
        expected=["svc-a"],
    )


def test_registered_with_hyphenated_alias() -> None:
    assert "rca_maxz" in TARGETS
    assert TARGETS.resolve("rca-maxz") == "rca_maxz"


def test_ranks_the_spiking_candidate_first() -> None:
    target = TARGETS.create("rca_maxz", {})
    out = target.run(_item())
    assert out.error is None
    assert out.output["ranked"][0] == "svc-a"
    assert out.metadata["max_abs_z"]["svc-a"] > out.metadata["max_abs_z"]["svc-b"]


def test_determinism_two_runs_identical() -> None:
    target = TARGETS.create("rca_maxz", {})
    first = target.run(_item())
    second = target.run(_item())
    assert first.output == second.output
    assert first.metadata == second.metadata
    assert target.is_deterministic() is True


def test_abstains_when_no_candidate_reaches_the_floor() -> None:
    target = TARGETS.create("rca_maxz", {})
    flat = EvalItem(
        id="rca-f",
        inputs={"candidates": ["svc-a", "svc-b"], "telemetry": _telemetry({})},
        expected=[],
    )
    out = target.run(flat)
    assert out.output == {"abstain": True}


def test_floor_is_configurable_and_validated() -> None:
    with pytest.raises(ValueError, match="z_floor"):
        TARGETS.create("rca_maxz", {"z_floor": -1})
    with pytest.raises(ValueError, match="z_floor"):
        TARGETS.create("rca_maxz", {"z_floor": float("nan")})
    lenient = TARGETS.create("rca_maxz", {"z_floor": 0.5})
    flat = EvalItem(
        id="rca-f",
        inputs={"candidates": ["svc-a", "svc-b"], "telemetry": _telemetry({"svc-a": 5.0})},
        expected=["svc-a"],
    )
    assert lenient.run(flat).output.get("ranked", [None])[0] == "svc-a"


def test_missing_inputs_are_errors_not_crashes() -> None:
    target = TARGETS.create("rca_maxz", {})
    assert target.run(EvalItem(id="x", inputs={})).error is not None
    no_telemetry = EvalItem(id="y", inputs={"candidates": ["svc-a"]})
    assert target.run(no_telemetry).error is not None

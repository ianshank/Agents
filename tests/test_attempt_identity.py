"""Attempt-identity contract for repeated-attempt reliability metrics.

The backwards-compatibility assertion here mirrors ADR 0031's trajectory
precedent: an appended field, no reordering, and result JSON that is
byte-identical when no attempt identity is present (``repetitions=1``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from eval_harness.core.types import EvalItem, ItemResult, RunResult, TargetOutput
from tests._trajectory_helpers import run_result


def test_repetitions_one_serializes_without_attempt_keys():
    """A `repetitions=1` run's item payload has no attempt-identity keys."""
    payload = run_result(TargetOutput(output="plain")).to_dict()
    item_payload = payload["items"][0]
    assert "attempt_index" not in item_payload
    assert "attempt_id" not in item_payload
    assert "item_run_id" not in item_payload
    assert set(item_payload) == {"id", "inputs", "expected", "output", "error", "latency_ms", "scores"}


def test_historical_positional_construction_still_works():
    """The three fields are appended last, so old positional calls keep working."""
    ir = ItemResult(EvalItem(id="i", inputs={}), TargetOutput(output="x"), [])
    assert ir.attempt_index is None
    assert ir.attempt_id is None
    assert ir.item_run_id is None


def test_attempt_identity_is_emitted_when_present():
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    item = EvalItem(id="i", inputs={})
    run = RunResult(
        run_id="r",
        config_name="c",
        items=[
            ItemResult(item, TargetOutput(output="a1"), attempt_index=0, attempt_id="i:0", item_run_id="r:i"),
            ItemResult(item, TargetOutput(output="a2"), attempt_index=1, attempt_id="i:1", item_run_id="r:i"),
        ],
        aggregate={},
        started_at=moment,
        finished_at=moment,
    )
    payload = run.to_dict()
    first, second = payload["items"]
    assert first["attempt_index"] == 0
    assert first["attempt_id"] == "i:0"
    assert first["item_run_id"] == "r:i"
    assert second["attempt_index"] == 1
    assert second["attempt_id"] == "i:1"
    # Both attempts of the same item share one item_run_id.
    assert first["item_run_id"] == second["item_run_id"]

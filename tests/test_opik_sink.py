"""Unit tests for OpikSink."""

from datetime import datetime, timezone

from eval_harness.core.types import EvalItem, ItemResult, TargetOutput, RunResult, ScoreAggregate, ScoreResult
from eval_harness.opik_client import NullOpikClient
from eval_harness.plugins import SINKS
from eval_harness.sinks import OpikSink


def test_opik_sink_registered() -> None:
    assert "opik" in SINKS.names()
    cls = SINKS.get("opik")
    assert cls is OpikSink


def test_opik_sink_emit_null_client() -> None:
    sink = OpikSink(enabled=False, project_name="test-proj")
    
    item = EvalItem(id="i1", inputs={"q": "hello"}, expected="hello")
    output = TargetOutput(output="hello")
    scores = [
        ScoreResult(name="exact_match", value=1.0, passed=True),
        ScoreResult(name="low_score", value=0.2, passed=False),
    ]
    ir = ItemResult(item=item, output=output, scores=scores)
    now = datetime.now(timezone.utc)
    
    run = RunResult(
        run_id="run_123",
        config_name="demo",
        items=[ir],
        aggregate={"exact_match": ScoreAggregate(mean=1.0, count=1, pass_rate=1.0)},
        started_at=now,
        finished_at=now,
    )

    sink.emit(run)
    assert isinstance(sink._client, NullOpikClient)
    assert len(sink._client.items) == 1
    assert sink._client.items[0]["scores"] == {"exact_match": 1.0, "low_score": 0.2}
    assert sink._client.flushed


def test_opik_sink_emit_with_threshold() -> None:
    sink = OpikSink(enabled=False, project_name="test-proj", min_value_to_log=0.5)
    
    item = EvalItem(id="i1", inputs={"q": "hello"})
    output = TargetOutput(output="hello")
    scores = [
        ScoreResult(name="exact_match", value=1.0, passed=True),
        ScoreResult(name="low_score", value=0.2, passed=False),
    ]
    ir = ItemResult(item=item, output=output, scores=scores)
    now = datetime.now(timezone.utc)
    
    run = RunResult(
        run_id="run_123",
        config_name="demo",
        items=[ir],
        aggregate={},
        started_at=now,
        finished_at=now,
    )

    sink.emit(run)
    assert sink._client.items[0]["scores"] == {"exact_match": 1.0}

from __future__ import annotations

from datetime import datetime, timezone

from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    RunResult,
    ScoreAggregate,
    ScoreResult,
    TargetOutput,
)
from eval_harness.datasets import InlineDataset, JsonlDataset, LangfuseDataset
from eval_harness.judges import MockJudge
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.plugins import SINKS, TARGETS
from eval_harness.sinks import JsonFileSink, LangfuseSink


# ---- judges ----
def test_mock_judge_default():
    assert MockJudge(default_score=0.3).evaluate("anything").score == 0.3


def test_mock_judge_rule_match():
    j = MockJudge(default_score=1.0, rules=[{"contains": "bad", "score": 0.1}])
    assert j.evaluate("this is bad").score == 0.1
    assert j.evaluate("this is fine").score == 1.0


# ---- targets ----
def test_echo_target_key():
    t = TARGETS.create("echo", {"output_key": "q"})
    assert t.run(EvalItem(id="1", inputs={"q": "hi"})).output == "hi"


def test_callable_target_dynamic_import():
    t = TARGETS.create("callable", {"path": "tests._sut:summarize"})
    out = t.run(EvalItem(id="1", inputs={"text": "x"}))
    assert out.output == "summary: x"
    assert out.latency_ms is not None


def test_callable_target_error_captured():
    t = TARGETS.create("callable", {"path": "tests._sut:boom"})
    out = t.run(EvalItem(id="1", inputs={}))
    assert out.output is None and "kaboom" in out.error


# ---- datasets ----
def test_inline_dataset():
    ds = InlineDataset(items=[{"id": "a", "inputs": {"x": 1}, "expected": 2}])
    items = list(ds.load())
    assert items[0].id == "a" and items[0].expected == 2


def test_jsonl_dataset(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"id":"a","inputs":{"x":1}}\n\n{"id":"b","inputs":{"x":2}}\n')
    items = list(JsonlDataset(path=str(p)).load())
    assert [i.id for i in items] == ["a", "b"]


def test_langfuse_dataset_with_client():
    client = NullLangfuseClient(dataset_items={"golden": [{"id": "z", "inputs": {"q": 1}}]})
    ds = LangfuseDataset(dataset_name="golden")
    ds.attach_client(client)
    items = list(ds.load())
    assert items[0].id == "z"


# ---- sinks ----
def _run():
    item = EvalItem(id="i", inputs={}, expected=None)
    ir = ItemResult(item=item, output=TargetOutput(output="o"), scores=[ScoreResult("acc", 1.0, True)])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return RunResult(
        run_id="r1",
        config_name="c",
        items=[ir],
        aggregate={"acc": ScoreAggregate(count=1, mean=1.0, pass_rate=1.0)},
        started_at=now,
        finished_at=now,
    )


def test_console_sink(capsys):
    SINKS.create("console", {}).emit(_run())
    assert "acc" in capsys.readouterr().out


def test_json_file_sink(tmp_path):
    out = tmp_path / "nested" / "r.json"
    JsonFileSink(path=str(out)).emit(_run())
    import json

    data = json.loads(out.read_text())
    assert data["run_id"] == "r1" and data["items"][0]["scores"][0]["name"] == "acc"


def test_langfuse_sink_logs_scores():
    client = NullLangfuseClient()
    sink = LangfuseSink()
    sink.attach_client(client)
    sink.emit(_run())
    assert len(client.scores) == 1 and client.flushed


def test_console_sink_verbose(capsys):
    """verbose=True appends per-item score lines to the output."""
    SINKS.create("console", {"verbose": True}).emit(_run())
    out = capsys.readouterr().out
    assert "acc" in out
    assert "i" in out  # item id appears in verbose output


def test_langfuse_sink_no_client_raises():
    """emit() without attach_client() raises RuntimeError."""
    import pytest

    sink = LangfuseSink()
    with pytest.raises(RuntimeError, match="no client"):
        sink.emit(_run())


def test_langfuse_sink_min_value_filter():
    """Scores below min_value_to_log are not forwarded to the client."""
    client = NullLangfuseClient()
    sink = LangfuseSink(min_value_to_log=0.5)
    sink.attach_client(client)
    # _run() has ScoreResult("acc", 1.0, True) — above 0.5 → logged
    sink.emit(_run())
    assert len(client.scores) == 1

    # Now emit a run whose score is below the threshold
    from datetime import datetime, timezone

    from eval_harness.core.types import (
        EvalItem,
        ItemResult,
        RunResult,
        ScoreAggregate,
        ScoreResult,
        TargetOutput,
    )

    low_item = ItemResult(
        item=EvalItem(id="low", inputs={}, expected=None),
        output=TargetOutput(output="o"),
        scores=[ScoreResult("acc", 0.1, False)],
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    low_run = RunResult(
        run_id="r2",
        config_name="c",
        items=[low_item],
        aggregate={"acc": ScoreAggregate(count=1, mean=0.1, pass_rate=0.0)},
        started_at=now,
        finished_at=now,
    )
    client2 = NullLangfuseClient()
    sink2 = LangfuseSink(min_value_to_log=0.5)
    sink2.attach_client(client2)
    sink2.emit(low_run)
    # Score 0.1 is below 0.5 → filtered out → nothing logged
    assert len(client2.scores) == 0


def test_echo_target_no_key():
    t = TARGETS.create("echo", {})
    inputs = {"q": "hi", "other": 1}
    assert t.run(EvalItem(id="1", inputs=inputs)).output == inputs


def test_callable_target_invalid_path():
    import pytest

    t = TARGETS.create("callable", {"path": "invalidpath"})
    with pytest.raises(ValueError, match="must be 'module:function'"):
        t.run(EvalItem(id="1", inputs={}))


def test_callable_target_pass_item():
    t = TARGETS.create("callable", {"path": "tests._sut:summarize_item", "pass_item": True})
    out = t.run(EvalItem(id="1", inputs={"text": "x"}))
    assert out.output == "summary_item: x"


def test_entry_point_plugins_loading():
    from unittest.mock import MagicMock, patch

    from eval_harness.plugins import load_entry_point_plugins

    mock_ep = MagicMock()
    mock_ep.name = "mock_plugin"

    mock_eps = MagicMock()
    mock_eps.select.return_value = [mock_ep]

    with patch("importlib.metadata.entry_points", return_value=mock_eps):
        load_entry_point_plugins()
        mock_ep.load.assert_called_once()

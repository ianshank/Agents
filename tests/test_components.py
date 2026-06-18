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
    ir = ItemResult(item=item, output=TargetOutput(output="o"),
                    scores=[ScoreResult("acc", 1.0, True)])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return RunResult(
        run_id="r1", config_name="c", items=[ir],
        aggregate={"acc": ScoreAggregate(count=1, mean=1.0, pass_rate=1.0)},
        started_at=now, finished_at=now,
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

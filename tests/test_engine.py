from __future__ import annotations

from datetime import datetime, timezone

from eval_harness.config import load_config_dict
from eval_harness.engine import EvalEngine
from eval_harness.gating import evaluate_gate
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.version import SCHEMA_VERSION


def _fixed_clock():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "run": {"name": "t", "run_id": "fixed-1", "seed": 1},
    "dataset": {
        "type": "inline",
        "params": {
            "items": [
                {"id": "1", "inputs": {"q": "reset password"}, "expected": "reset password"},
                {"id": "2", "inputs": {"q": "cancel plan"}, "expected": "cancel plan"},
            ]
        },
    },
    "target": {"type": "echo", "params": {"output_key": "q"}},
    "scorers": [
        {"type": "exact_match", "params": {"name": "acc"}},
        {"type": "contains", "params": {"name": "has_reset", "substring": "reset"}},
        {"type": "llm_judge", "params": {"name": "quality", "threshold": 0.6}},
    ],
    "judge": {"type": "mock", "params": {"default_score": 0.8}},
    "sinks": [{"type": "langfuse", "params": {}}],
}


def _engine(cfg=None, client=None):
    config = load_config_dict(cfg or dict(CONFIG))
    engine = EvalEngine.from_config(config, langfuse_client=client or NullLangfuseClient())
    engine.clock = _fixed_clock
    return config, engine


def test_engine_end_to_end_aggregate():
    _, engine = _engine()
    run = engine.run()
    assert run.run_id == "fixed-1"
    assert len(run.items) == 2
    # exact_match: both outputs equal expected -> mean 1.0
    assert run.aggregate["acc"].mean == 1.0
    # contains 'reset': only item 1 -> pass_rate 0.5
    assert run.aggregate["has_reset"].pass_rate == 0.5
    # judge default 0.8 for both -> mean 0.8
    assert abs(run.aggregate["quality"].mean - 0.8) < 1e-9


def test_engine_writes_scores_to_langfuse():
    client = NullLangfuseClient()
    _, engine = _engine(client=client)
    engine.run()
    # 3 scorers x 2 items = 6 scores
    assert len(client.scores) == 6
    assert client.flushed


def test_sampling_zero_rate_empty():
    cfg = dict(CONFIG)
    cfg["run"] = {"name": "t", "run_id": "z", "seed": 1, "sample_rate": 0.0}
    _, engine = _engine(cfg)
    run = engine.run()
    assert run.items == []


def test_sampling_is_deterministic():
    cfg = dict(CONFIG)
    cfg["run"] = {"name": "t", "seed": 42, "sample_rate": 0.5}
    runs = []
    for _ in range(2):
        _, engine = _engine(dict(cfg))
        runs.append([ir.item.id for ir in engine.run().items])
    assert runs[0] == runs[1]  # same seed -> same sample


def test_gate_pass():
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "acc", "metric": "mean", "min": 0.9}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert result.passed


def test_gate_fail():
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "has_reset", "metric": "pass_rate", "min": 0.9}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert not result.passed and result.failures


def test_gate_missing_score():
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "nope", "metric": "mean", "min": 0.1}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert not result.passed


def test_gate_none_passes():
    _config, engine = _engine()
    assert evaluate_gate(None, engine.run()).passed


def test_gate_pass_rate_none_fails():
    """Metric='pass_rate' on an aggregate with pass_rate=None → failure with informative message."""
    from datetime import timezone

    from eval_harness.config.models import GateConfig, GateRule
    from eval_harness.core.types import RunResult, ScoreAggregate

    run = RunResult(
        run_id="r",
        config_name="c",
        items=[],
        aggregate={"acc": ScoreAggregate(count=1, mean=0.9, pass_rate=None)},
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    gate = GateConfig(rules=[GateRule(score="acc", metric="pass_rate", min=0.5)])
    result = evaluate_gate(gate, run)
    assert not result.passed
    assert any("pass_rate" in f for f in result.failures)


def test_gate_max_violated_fails():
    """A rule with max=0.5 fails when observed mean=1.0 exceeds it."""
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "acc", "metric": "mean", "max": 0.5}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert not result.passed
    assert any("above max" in f for f in result.failures)


def test_engine_scorer_exception_handling():
    from unittest.mock import MagicMock

    import pytest

    from eval_harness.core.interfaces import Scorer

    # 1. Without fail_fast
    cfg = dict(CONFIG)
    cfg["run"] = {"name": "test-fail-fast-false", "fail_fast": False}
    bad_scorer = MagicMock(spec=Scorer)
    bad_scorer.name = "broken_scorer"
    bad_scorer.score.side_effect = ValueError("simulated scorer failure")

    config = load_config_dict(cfg)
    engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
    engine.scorers = [bad_scorer]

    run = engine.run()
    assert len(run.items) == 2
    for item in run.items:
        score = item.scores[0]
        assert score.name == "broken_scorer"
        assert score.value == 0.0
        assert not score.passed
        assert "scorer error: simulated scorer failure" in score.comment

    # 2. With fail_fast=True
    cfg_fast = dict(CONFIG)
    cfg_fast["run"] = {"name": "test-fail-fast-true", "fail_fast": True}
    config_fast = load_config_dict(cfg_fast)
    engine_fast = EvalEngine.from_config(config_fast, langfuse_client=NullLangfuseClient())
    engine_fast.scorers = [bad_scorer]

    with pytest.raises(ValueError, match="simulated scorer failure"):
        engine_fast.run()


def test_engine_links_trace_to_dataset_item():
    from unittest.mock import MagicMock, patch

    with patch("eval_harness.langfuse_client.langfuse_context.get_current_trace_id", return_value="trace-123"):
        # Case A: run_id is set
        cfg = dict(CONFIG)
        cfg["run"] = {"name": "test-run", "run_id": "custom-run-id"}
        config = load_config_dict(cfg)
        mock_client = MagicMock()
        engine = EvalEngine.from_config(config, langfuse_client=mock_client)
        engine.run()

        assert mock_client.link_dataset_item.call_count == 2
        mock_client.link_dataset_item.assert_any_call(item_id="1", trace_id="trace-123", run_name="custom-run-id")

        # Case B: run_id is None -> fallback to name
        cfg_no_id = dict(CONFIG)
        cfg_no_id["run"] = {"name": "test-fallback-name", "run_id": None}
        config_no_id = load_config_dict(cfg_no_id)
        mock_client_no_id = MagicMock()
        engine_no_id = EvalEngine.from_config(config_no_id, langfuse_client=mock_client_no_id)
        engine_no_id.run()

        assert mock_client_no_id.link_dataset_item.call_count == 2
        mock_client_no_id.link_dataset_item.assert_any_call(
            item_id="1", trace_id="trace-123", run_name="test-fallback-name"
        )

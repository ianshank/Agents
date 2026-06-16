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

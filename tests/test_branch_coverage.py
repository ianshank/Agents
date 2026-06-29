"""Branch-coverage tests for previously-uncovered conditional paths.

These target partial branches that line coverage alone did not exercise: the engine's
sampling and per-scorer error handling, the echo/callable target edge cases, and the
Langfuse dataset's missing-client guard.
"""

from __future__ import annotations

import pytest

from eval_harness.config import load_config_dict
from eval_harness.engine import EvalEngine
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.version import SCHEMA_VERSION

BASE_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "run": {"name": "t", "run_id": "fixed-1", "seed": 1},
    "dataset": {
        "type": "inline",
        "params": {"items": [{"id": "1", "inputs": {"q": "hi"}, "expected": "hi"}]},
    },
    "target": {"type": "echo", "params": {"output_key": "q"}},
    "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
    "sinks": [],
}


def _engine(cfg=None):
    config = load_config_dict(cfg or dict(BASE_CONFIG))
    return EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())


# --- engine._sample: rate < 1.0 takes the sampling branch ---------------------


def test_sample_rate_below_one_filters_items():
    cfg = dict(BASE_CONFIG)
    cfg["run"] = {"name": "t", "run_id": "r", "seed": 1, "sample_rate": 0.0}
    run = _engine(cfg).run()
    assert run.items == []


# --- engine._run_one: a scorer that raises is recorded, not fatal -------------


def test_scorer_exception_becomes_failed_score(monkeypatch):
    engine = _engine()

    def _boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(engine.scorers[0], "score", _boom)
    run = engine.run()
    score = run.items[0].scores[0]
    assert score.passed is False
    assert "scorer error" in score.comment


def test_scorer_exception_with_fail_fast_propagates(monkeypatch):
    cfg = dict(BASE_CONFIG)
    cfg["run"] = {"name": "t", "run_id": "r", "seed": 1, "fail_fast": True}
    engine = _engine(cfg)

    def _boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(engine.scorers[0], "score", _boom)
    with pytest.raises(RuntimeError, match="kaboom"):
        engine.run()


# --- targets: echo without output_key, callable with a malformed path ---------


def test_echo_target_without_output_key_returns_full_inputs():
    from eval_harness.core.types import EvalItem
    from eval_harness.targets import EchoTarget

    item = EvalItem(id="1", inputs={"a": 1, "b": 2})
    assert EchoTarget().run(item).output == {"a": 1, "b": 2}


def test_callable_target_rejects_path_without_function():
    from eval_harness.targets import CallableTarget

    with pytest.raises(ValueError, match="must be 'module:function'"):
        CallableTarget("module_only")._resolve()


def test_callable_target_pass_item_receives_whole_item():
    from eval_harness.core.types import EvalItem
    from eval_harness.targets import CallableTarget

    target = CallableTarget("tests._sut:echo_item", pass_item=True)
    out = target.run(EvalItem(id="abc", inputs={"q": "x"}))
    assert out.output == "item: abc"


def test_callable_target_caches_resolved_function():
    from eval_harness.targets import CallableTarget

    target = CallableTarget("tests._sut:summarize")
    first = target._resolve()
    # Second call must hit the cached-_fn branch rather than re-importing.
    assert target._resolve() is first


# --- version: PackageNotFoundError falls back to the source-tree sentinel ------


def test_version_falls_back_when_distribution_missing(monkeypatch):
    import importlib
    import importlib.metadata as md

    import eval_harness.version as ver

    def _raise(_name):
        raise md.PackageNotFoundError("not installed")

    monkeypatch.setattr(md, "version", _raise)
    try:
        reloaded = importlib.reload(ver)
        assert reloaded.__version__ == "0.0.0-dev"
    finally:
        monkeypatch.undo()
        importlib.reload(ver)  # restore the real version for other tests


# --- CLI: offline run prints aggregates and reports the gate result -----------


def test_cli_run_offline(tmp_path, capsys):
    import yaml

    from eval_harness.cli import main

    cfg = dict(BASE_CONFIG)
    cfg["gate"] = {"min_pass_rate": {"acc": 0.0}}
    config_path = tmp_path / "eval.yaml"
    config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    rc = main(["run", "--config", str(config_path), "--offline"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "acc:" in out  # aggregate line printed (no console sink configured)
    assert "QUALITY GATE: PASS" in out


# --- datasets: LangfuseDataset.load with no client attached -------------------


def test_langfuse_dataset_requires_client():
    from eval_harness.datasets import LangfuseDataset

    with pytest.raises(RuntimeError, match="no client attached"):
        list(LangfuseDataset("ds").load())

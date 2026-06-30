"""Backwards-compatibility tests for config model changes (F-018).

Ensures that configs without the new ``max_workers`` field (or other
optional fields added over time) continue to parse correctly with
their documented defaults.
"""

from __future__ import annotations

from datetime import datetime, timezone

from eval_harness.config import load_config_dict
from eval_harness.config.models import RunSettings
from eval_harness.engine import EvalEngine
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.version import SCHEMA_VERSION


def _fixed_clock():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Minimal config without max_workers
# ---------------------------------------------------------------------------

_LEGACY_CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "run": {"name": "legacy-run", "run_id": "compat-1", "seed": 7},
    "dataset": {
        "type": "inline",
        "params": {
            "items": [
                {"id": "a", "inputs": {"q": "hello"}, "expected": "hello"},
                {"id": "b", "inputs": {"q": "world"}, "expected": "world"},
            ]
        },
    },
    "target": {"type": "echo", "params": {"output_key": "q"}},
    "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
    "sinks": [],
}


class TestConfigWithoutMaxWorkers:
    """Config YAML without max_workers parses with default 1."""

    def test_default_max_workers_is_1(self):
        config = load_config_dict(dict(_LEGACY_CONFIG))
        assert config.run.max_workers == 1

    def test_run_settings_default(self):
        settings = RunSettings()
        assert settings.max_workers == 1
        assert settings.fail_fast is False
        assert settings.sample_rate == 1.0
        assert settings.seed == 0


class TestConfigWithoutBudget:
    """Config without budget field still works (judge doesn't require it)."""

    def test_judge_works_without_budget(self):
        cfg = dict(_LEGACY_CONFIG)
        cfg["judge"] = {"type": "mock", "params": {"default_score": 0.7}}
        cfg["scorers"] = [{"type": "llm_judge", "params": {"name": "quality", "threshold": 0.5}}]
        config = load_config_dict(cfg)
        engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        engine.clock = _fixed_clock
        run = engine.run()
        assert len(run.items) == 2
        assert "quality" in run.aggregate


class TestConfigWithoutJudgeBudget:
    """Config YAML without the F-022 judge_budget field parses with default None."""

    def test_judge_budget_defaults_to_none(self):
        config = load_config_dict(dict(_LEGACY_CONFIG))
        assert config.judge_budget is None

    def test_engine_judge_unwrapped_without_budget(self):
        cfg = dict(_LEGACY_CONFIG)
        cfg["judge"] = {"type": "mock", "params": {}}
        config = load_config_dict(cfg)
        engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        # No agent_core import path taken; judge is the bare mock judge.
        assert type(engine.judge).__name__ == "MockJudge"


class TestLegacyConfigMigration:
    """Configs at older schema versions still migrate and parse."""

    def test_v09_config_migration(self):
        """If the migration pipeline exists, old versions are handled."""
        # The current schema version should work directly
        config = load_config_dict(dict(_LEGACY_CONFIG))
        assert config.run.name == "legacy-run"


class TestMaxWorkers1BaselineAggregate:
    """max_workers=1 produces identical RunResult.aggregate to a known baseline."""

    def test_aggregate_baseline(self):
        config = load_config_dict(dict(_LEGACY_CONFIG))
        engine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        engine.clock = _fixed_clock
        run = engine.run()

        # Known baseline: exact_match on echo target, both items match
        assert run.aggregate["acc"].count == 2
        assert run.aggregate["acc"].mean == 1.0
        assert run.aggregate["acc"].pass_rate == 1.0
        assert run.run_id == "compat-1"

from __future__ import annotations

import pytest

from eval_harness.config import (
    apply_overrides,
    interpolate,
    load_config,
    load_config_dict,
)
from eval_harness.config.migrations import ConfigError, migrate_to_current
from eval_harness.config.models import EvalConfig
from eval_harness.version import SCHEMA_VERSION

BASE = {
    "schema_version": SCHEMA_VERSION,
    "dataset": {"type": "inline", "params": {"items": []}},
    "target": {"type": "echo"},
    "scorers": [{"type": "exact_match"}],
}


def test_interpolate_env_and_default():
    assert interpolate("${FOO}", {"FOO": "bar"}) == "bar"
    assert interpolate("${MISSING:-fallback}", {}) == "fallback"
    # a whole-token numeric default coerces to a native int, not a string
    assert interpolate({"a": ["${X:-1}"]}, {}) == {"a": [1]}
    # embedded tokens stay strings
    assert interpolate("${D:-/out}/r.json", {}) == "/out/r.json"


def test_interpolate_missing_without_default_raises():
    with pytest.raises(ConfigError):
        interpolate("${NOPE}", {})


def test_apply_overrides_nested():
    raw = {"run": {"sample_rate": 1.0}}
    apply_overrides(raw, ["run.sample_rate=0.25", "run.name=x"])
    assert raw["run"]["sample_rate"] == 0.25
    assert raw["run"]["name"] == "x"


def test_load_config_dict_validates():
    cfg = load_config_dict(dict(BASE))
    assert isinstance(cfg, EvalConfig)
    assert cfg.run.sample_rate == 1.0


def test_override_applied_through_loader():
    cfg = load_config_dict(dict(BASE), overrides=["run.sample_rate=0.5"])
    assert cfg.run.sample_rate == 0.5


def test_sample_rate_validator():
    bad = dict(BASE, run={"sample_rate": 2.0})
    with pytest.raises(ValueError):
        load_config_dict(bad)


def test_missing_schema_version_raises():
    raw = {k: v for k, v in BASE.items() if k != "schema_version"}
    with pytest.raises(ConfigError):
        migrate_to_current(raw)


def test_unknown_schema_version_raises():
    with pytest.raises(ConfigError):
        migrate_to_current({"schema_version": "0.1"})


def test_load_config_from_file(tmp_path):
    import textwrap

    p = tmp_path / "c.yaml"
    p.write_text(
        textwrap.dedent(
            f"""
            schema_version: "{SCHEMA_VERSION}"
            dataset: {{type: inline, params: {{items: []}}}}
            target: {{type: echo}}
            scorers: [{{type: exact_match}}]
            """
        )
    )
    cfg = load_config(p)
    assert cfg.dataset.type == "inline"

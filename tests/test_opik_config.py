"""Unit tests for OpikConfig schema integration."""

from eval_harness.config import load_config_dict
from eval_harness.config.models import EvalConfig, OpikConfig


def test_opik_config_defaults() -> None:
    cfg = OpikConfig()
    assert not cfg.enabled
    assert cfg.project_name == "eval-harness"
    assert cfg.workspace is None
    assert cfg.track_targets


def test_eval_config_with_opik_block() -> None:
    raw = {
        "schema_version": "1.0",
        "run": {"name": "test_run"},
        "dataset": {"type": "inline", "params": {"items": []}},
        "target": {"type": "echo", "params": {}},
        "opik": {
            "enabled": True,
            "project_name": "custom-opik-proj",
            "workspace": "my-workspace",
        },
    }
    config = load_config_dict(raw)
    assert isinstance(config, EvalConfig)
    assert config.opik is not None
    assert config.opik.enabled
    assert config.opik.project_name == "custom-opik-proj"
    assert config.opik.workspace == "my-workspace"

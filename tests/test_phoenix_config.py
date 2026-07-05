"""PhoenixConfig — Arize Phoenix observability config (spike).

Offline-only: validates the schema and backwards-compatibility. No Phoenix SDK
is imported here (config is pure data), so these run in the air-gapped suite.
"""

from __future__ import annotations

from typing import Any

from eval_harness.config.models import EvalConfig, PhoenixConfig
from eval_harness.version import SCHEMA_VERSION


def _minimal_eval_config(**extra: Any) -> EvalConfig:
    """A structurally-valid EvalConfig; component types need not be registered to validate."""
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset": {"type": "inline"},
        "target": {"type": "echo"},
        **extra,
    }
    return EvalConfig.model_validate(data)


def test_phoenix_config_defaults_are_safe_and_off() -> None:
    cfg = PhoenixConfig()
    assert cfg.enabled is False  # off by default → existing runs are unaffected
    assert cfg.tracing is True
    assert cfg.auto_instrument is True
    assert cfg.batch is True
    assert cfg.project_name  # non-empty default, overridable (no magic literal in code paths)


def test_phoenix_config_fields_override() -> None:
    cfg = PhoenixConfig(
        enabled=True,
        project_name="my-proj",
        tracing=False,
        auto_instrument=False,
        batch=False,
    )
    assert cfg.enabled is True
    assert cfg.project_name == "my-proj"
    assert cfg.tracing is False
    assert cfg.auto_instrument is False
    assert cfg.batch is False


def test_eval_config_without_phoenix_block_is_none() -> None:
    # Absent block → None: pre-existing configs keep validating; SCHEMA_VERSION untouched.
    cfg = _minimal_eval_config()
    assert cfg.phoenix is None


def test_eval_config_accepts_phoenix_block() -> None:
    cfg = _minimal_eval_config(phoenix={"enabled": True, "project_name": "p"})
    assert cfg.phoenix is not None
    assert cfg.phoenix.enabled is True
    assert cfg.phoenix.project_name == "p"

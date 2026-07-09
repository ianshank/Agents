"""The `run` command activates Phoenix tracing when configured — offline.

Heavy collaborators (engine, gate, config loader) are stubbed; this test asserts
only the tracing-activation wiring, so it needs no network and no Phoenix SDK.
"""

from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import Any

import eval_harness.cli as cli
from eval_harness.config.models import EvalConfig, PhoenixConfig
from eval_harness.version import SCHEMA_VERSION


class _FakeEngine:
    @classmethod
    def from_config(cls, config, **kwargs):
        return SimpleNamespace(run=lambda: SimpleNamespace(aggregate={}))


def _eval_config(**data: Any) -> EvalConfig:
    return EvalConfig.model_validate(data)


def _stub_run_pipeline(monkeypatch, cfg, captured):
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "configure_tracing", lambda pc: captured.__setitem__("pc", pc))
    monkeypatch.setattr(cli, "EvalEngine", _FakeEngine)
    monkeypatch.setattr(cli, "evaluate_gate", lambda gate, run: SimpleNamespace(passed=True, failures=[]))


def test_run_activates_tracing_with_phoenix_config(monkeypatch) -> None:
    cfg = _eval_config(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "x"},
        target={"type": "y"},
        phoenix=PhoenixConfig(enabled=True, project_name="proj"),
    )
    captured: dict = {}
    _stub_run_pipeline(monkeypatch, cfg, captured)

    rc = cli._cmd_run(Namespace(config="cfg.yaml", overrides=[], offline=True))

    assert rc == 0
    assert captured["pc"] is cfg.phoenix
    assert cfg.phoenix is not None
    assert cfg.phoenix.enabled is True


def test_run_passes_none_when_no_phoenix_block(monkeypatch) -> None:
    cfg = _eval_config(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "x"},
        target={"type": "y"},
    )  # no phoenix block → tracing is a no-op
    captured: dict = {}
    _stub_run_pipeline(monkeypatch, cfg, captured)

    rc = cli._cmd_run(Namespace(config="cfg.yaml", overrides=[], offline=True))

    assert rc == 0
    assert captured["pc"] is None

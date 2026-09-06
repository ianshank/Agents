"""Tests for gate-policy file / env / CLI overlay (operator seams)."""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

import pytest

from agent_core.config import ConfigError
from agent_core.gate_policy_io import (
    OPERATOR_FIELDS,
    GatePolicyIOConfig,
    env_name,
    load_policy_file,
    overlay_from_environ,
    resolve_policy,
)
from agent_core.merge_gate import GatePolicyConfig
from agent_core.merge_gate_ci import main


@pytest.fixture(autouse=True)
def _isolate_merge_gate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    io = GatePolicyIOConfig()
    for name in OPERATOR_FIELDS:
        monkeypatch.delenv(env_name(name, io), raising=False)
    monkeypatch.delenv(io.policy_file_env_var, raising=False)
    monkeypatch.delenv(env_name("protected_auto_merge", io), raising=False)


def _healthy_store(path: Path):
    from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

    store = OutcomeStore(path)
    for i in range(1000):
        high = i % 2 == 0
        store.append(
            OutcomeRecord(
                change_id=f"c{i}",
                domain="core",
                raw_confidence=0.96 if high else 0.04,
                merged_at="2026-01-01T00:00:00+00:00",
                label=high,
                label_source=LabelSource.HUMAN_AUDIT.value,
                labeled_at="2026-01-02T00:00:00+00:00",
            )
        )
    return store


def _ctx_file(tmp_path: Path) -> str:
    path = tmp_path / "ctx.json"
    path.write_text(
        json.dumps(
            {
                "mech_pass": True,
                "touches_protected": False,
                "raw_confidence": 0.96,
                "domain": "core",
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_operator_fields_lockstep_gate_policy_minus_protected() -> None:
    names = {f.name for f in fields(GatePolicyConfig)} - {"protected_auto_merge"}
    assert set(OPERATOR_FIELDS) == names


def test_empty_env_is_ignored() -> None:
    io = GatePolicyIOConfig()
    env = {env_name(n, io): "" for n in OPERATOR_FIELDS}
    env[env_name("protected_auto_merge", io)] = ""
    assert overlay_from_environ(env, io) == {}


def test_env_overlay_parses_int_and_float() -> None:
    io = GatePolicyIOConfig()
    overlay = overlay_from_environ(
        {
            env_name("risk_target", io): "0.11",
            env_name("min_calibration_n", io): "333",
        },
        io,
    )
    assert overlay["risk_target"] == 0.11
    assert overlay["min_calibration_n"] == 333
    assert isinstance(overlay["min_calibration_n"], int)


def test_env_refuses_protected_auto_merge() -> None:
    io = GatePolicyIOConfig()
    with pytest.raises(ConfigError, match="protected_auto_merge"):
        overlay_from_environ({env_name("protected_auto_merge", io): "true"}, io)


def test_file_unknown_key_is_config_error(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"nope": 1.0}), encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown"):
        load_policy_file(path)


def test_file_refuses_protected_auto_merge(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"protected_auto_merge": True}), encoding="utf-8")
    with pytest.raises(ConfigError, match="protected_auto_merge"):
        load_policy_file(path)


def test_file_invalid_json_is_config_error(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_policy_file(path)


def test_file_int_field_accepts_whole_float(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"min_calibration_n": 200.0}), encoding="utf-8")
    assert load_policy_file(path)["min_calibration_n"] == 200


def test_file_bad_int_and_float_are_config_errors(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"min_calibration_n": "nope"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="must be an int"):
        load_policy_file(path)
    path.write_text(json.dumps({"risk_target": "nope"}), encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a float"):
        load_policy_file(path)


def test_file_must_be_a_json_object(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError, match="JSON object"):
        load_policy_file(path)


def test_resolve_order_file_then_env_then_cli(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"risk_target": 0.10, "max_ece": 0.40}), encoding="utf-8")
    io = GatePolicyIOConfig()
    cfg = resolve_policy(
        file_values=load_policy_file(path),
        environ={env_name("risk_target", io): "0.11", env_name("max_ece", io): "0.41"},
        cli={"risk_target": 0.12},
        io_cfg=io,
    )
    assert cfg.risk_target == 0.12  # CLI wins
    assert cfg.max_ece == 0.41  # env wins over file
    assert cfg.protected_auto_merge is False


def test_cli_none_does_not_mask_env() -> None:
    io = GatePolicyIOConfig()
    cfg = resolve_policy(
        cli={"risk_target": None},
        environ={env_name("risk_target", io): "0.11"},
        io_cfg=io,
    )
    assert cfg.risk_target == 0.11


def test_main_honours_env_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _healthy_store(tmp_path / "s.jsonl")
    argv = ["--store", str(store.path), "--context", _ctx_file(tmp_path)]
    assert main(argv) == 0
    monkeypatch.setenv("MERGE_GATE_MIN_CALIBRATION_N", "100000")
    assert main(argv) == 10  # ESCALATE: floor unreachable


def test_main_policy_file_and_cli_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _healthy_store(tmp_path / "s.jsonl")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"min_calibration_n": 100000}), encoding="utf-8")
    argv = ["--store", str(store.path), "--context", _ctx_file(tmp_path)]
    assert main([*argv, "--policy-file", str(policy)]) == 10
    monkeypatch.setenv("MERGE_GATE_MIN_CALIBRATION_N", "100000")
    assert main([*argv, "--min-calibration-n", "200"]) == 0  # CLI restores merge


def test_main_policy_file_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _healthy_store(tmp_path / "s.jsonl")
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"min_calibration_n": 100000}), encoding="utf-8")
    monkeypatch.setenv("MERGE_GATE_POLICY_FILE", str(policy))
    argv = ["--store", str(store.path), "--context", _ctx_file(tmp_path)]
    assert main(argv) == 10


def test_main_refuses_protected_auto_merge_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _healthy_store(tmp_path / "s.jsonl")
    monkeypatch.setenv("MERGE_GATE_PROTECTED_AUTO_MERGE", "true")
    argv = ["--store", str(store.path), "--context", _ctx_file(tmp_path)]
    assert main(argv) == 2

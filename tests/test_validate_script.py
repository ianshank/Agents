#!/usr/bin/env python3
"""Tests for scripts/validate.py — features.yaml schema/DAG/git/command validator."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import validate as vs
import yaml

# ---------------------------------------------------------------------------
# Pure logic: DFS cycle detection
# ---------------------------------------------------------------------------


def test_detect_cycles_none() -> None:
    adj = {"A": ["B"], "B": [], "C": ["A", "B"]}
    assert vs._detect_cycles(adj, {"A", "B", "C"}) == []


def test_detect_cycles_two_node_loop() -> None:
    adj = {"A": ["B"], "B": ["A"]}
    cycles = vs._detect_cycles(adj, {"A", "B"})
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}


def test_detect_cycles_self_loop() -> None:
    cycles = vs._detect_cycles({"A": ["A"]}, {"A"})
    assert cycles and cycles[0][0] == "A"


def test_detect_cycles_ignores_unknown_neighbours() -> None:
    # Unknown dep is the missing-edge check's job, not a crash or a cycle.
    assert vs._detect_cycles({"A": ["GHOST"]}, {"A"}) == []


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_features_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "features.yaml"
    p.write_text(yaml.safe_dump({"features": [{"id": "F-001"}]}), encoding="utf-8")
    assert vs._load_features(p)["features"][0]["id"] == "F-001"


@pytest.mark.parametrize("payload", ["- just\n- a list\n", "no_features_key: true\n"])
def test_load_features_rejects_bad_shapes(tmp_path: Path, payload: str) -> None:
    p = tmp_path / "features.yaml"
    p.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="features"):
        vs._load_features(p)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_validate_schema_missing_file_skips(tmp_path: Path) -> None:
    assert vs._validate_schema({"features": []}, tmp_path / "nope.json") == []


def test_validate_schema_reports_violations(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {"features": {"type": "array"}},
        "required": ["features"],
    }
    sp = tmp_path / "schema.json"
    sp.write_text(json.dumps(schema), encoding="utf-8")
    assert vs._validate_schema({"features": []}, sp) == []
    errors = vs._validate_schema({"features": "not-a-list"}, sp)
    assert errors and "Schema:" in errors[0]


# ---------------------------------------------------------------------------
# DAG checks
# ---------------------------------------------------------------------------


def _feat(fid: str, **kw: Any) -> dict[str, Any]:
    return {"id": fid, "name": fid, "status": "todo", **kw}


def test_check_dag_clean() -> None:
    feats = [_feat("A"), _feat("B", depends_on=["A"])]
    assert vs._check_dag(feats) == []


def test_check_dag_unknown_dep_and_cycle() -> None:
    feats = [
        _feat("A", depends_on=["GHOST"]),
        _feat("B", depends_on=["C"]),
        _feat("C", depends_on=["B"]),
    ]
    errors = vs._check_dag(feats)
    assert any("unknown feature GHOST" in e for e in errors)
    assert any("cycle detected" in e for e in errors)


# ---------------------------------------------------------------------------
# Git ref verification (runs against this repository)
# ---------------------------------------------------------------------------


def test_check_git_refs_resolvable_and_absent_ref() -> None:
    feats = [_feat("A", implemented_in="HEAD"), _feat("B")]
    assert vs._check_git_refs(feats, strict=True) == []


def test_check_git_refs_unresolvable_strict_vs_lenient() -> None:
    feats = [_feat("A", implemented_in="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")]
    assert vs._check_git_refs(feats, strict=False) == []
    errors = vs._check_git_refs(feats, strict=True)
    assert errors and "does not resolve" in errors[0]


# ---------------------------------------------------------------------------
# Validation command execution
# ---------------------------------------------------------------------------


def test_route_to_active_python_rebinds_bare_interpreter() -> None:
    routed = vs._route_to_active_python("python -c pass")
    assert routed.startswith(f'"{sys.executable}" ')
    assert vs._route_to_active_python("python3 x.py").startswith(f'"{sys.executable}" ')
    assert vs._route_to_active_python("pytest -q") == "pytest -q"


def test_run_validation_command_missing_is_error() -> None:
    err = vs._run_validation_command(_feat("F-X", status="done"))
    assert err is not None and "no validation_command" in err


def test_run_validation_command_pass_and_fail() -> None:
    ok = _feat("F-OK", status="done", validation_command='python -c "pass"')
    assert vs._run_validation_command(ok) is None
    bad = _feat(
        "F-BAD",
        status="done",
        validation_command="python -c \"import sys; print('boom'); sys.exit(3)\"",
    )
    err = vs._run_validation_command(bad)
    assert err is not None and "F-BAD" in err and "(3)" in err and "boom" in err


def test_run_validation_commands_tier_filtering() -> None:
    feats = [
        _feat("F-1", status="done", tier="fast", validation_command='python -c "pass"'),
        _feat("F-2", status="done", tier="full", validation_command='python -c "pass"'),
        _feat("F-3", status="todo", tier="fast"),
    ]
    errors, ran, skipped = vs._run_validation_commands(feats, selected_tiers={"fast"})
    assert (errors, ran, skipped) == ([], 1, 1)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _write_features(tmp_path: Path, features: list[dict[str, Any]]) -> Path:
    p = tmp_path / "features.yaml"
    p.write_text(yaml.safe_dump({"features": features}), encoding="utf-8")
    return p


def test_main_missing_features_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert vs.main(["--features", str(tmp_path / "absent.yaml")]) == 2
    assert "not found" in capsys.readouterr().out


def test_main_unparseable_features_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "features.yaml"
    p.write_text("just a scalar\n", encoding="utf-8")
    assert vs.main(["--features", str(p)]) == 2
    assert "Failed to load" in capsys.readouterr().out


def test_main_check_single_feature(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write_features(
        tmp_path,
        [_feat("F-1", status="done", validation_command='python -c "pass"')],
    )
    assert vs.main(["--features", str(p), "--check", "F-1"]) == 0
    assert "F-1: OK" in capsys.readouterr().out
    assert vs.main(["--features", str(p), "--check", "F-404"]) == 1
    assert "unknown feature" in capsys.readouterr().out


def test_main_all_green_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write_features(
        tmp_path,
        [
            _feat("F-1", status="done", tier="fast", validation_command='python -c "pass"'),
            _feat("F-2", status="todo", depends_on=["F-1"]),
        ],
    )
    assert vs.main(["--features", str(p), "--schema", str(tmp_path / "none.json")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("OK: 1 done")


def test_main_collects_failures(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write_features(
        tmp_path,
        [
            _feat("F-1", status="done", tier="fast", validation_command='python -c "import sys; sys.exit(1)"'),
            _feat("F-2", status="todo", depends_on=["GHOST"]),
        ],
    )
    assert vs.main(["--features", str(p), "--schema", str(tmp_path / "none.json")]) == 1
    out = capsys.readouterr().out
    assert "VALIDATION FAILED" in out
    assert "GHOST" in out and "F-1" in out

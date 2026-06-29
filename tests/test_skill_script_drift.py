#!/usr/bin/env python3
"""Tests for the skill-script drift guard (``scripts/check_skill_script_drift.py``)."""

from __future__ import annotations

from pathlib import Path

import check_skill_script_drift as drift
import pytest

CANON = "scripts/validate_skill.py"
COPY = "skills/demo/scripts/validate_skill.py"
TRACKED = {CANON: (COPY,)}


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# check_drift: per-pair logic
# ---------------------------------------------------------------------------


def test_identical_copy_is_ok(tmp_path: Path) -> None:
    _write(tmp_path, CANON, "print('hi')\n")
    _write(tmp_path, COPY, "print('hi')\n")
    results = drift.check_drift(TRACKED, root=tmp_path)
    assert [r.status for r in results] == ["ok"]
    assert results[0].ok is True


def test_diverged_copy_is_drift(tmp_path: Path) -> None:
    _write(tmp_path, CANON, "print('hi')\n")
    _write(tmp_path, COPY, "print('DIFFERENT')\n")
    (result,) = drift.check_drift(TRACKED, root=tmp_path)
    assert result.status == "drift"
    assert result.ok is False


def test_missing_copy_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, CANON, "x = 1\n")
    (result,) = drift.check_drift(TRACKED, root=tmp_path)
    assert result.status == "missing_copy"


def test_missing_canonical_is_reported(tmp_path: Path) -> None:
    _write(tmp_path, COPY, "x = 1\n")
    (result,) = drift.check_drift(TRACKED, root=tmp_path)
    assert result.status == "missing_canonical"


def test_empty_tracking_returns_no_results(tmp_path: Path) -> None:
    assert drift.check_drift({}, root=tmp_path) == []


# ---------------------------------------------------------------------------
# Real repository: the actual vendored copies must already be in sync
# ---------------------------------------------------------------------------


def test_real_repo_copies_are_in_sync() -> None:
    results = drift.check_drift()
    assert results, "expected at least one tracked duplicate"
    drifted = [r for r in results if not r.ok]
    assert not drifted, f"vendored skill copies drifted: {[r.copy for r in drifted]}"


# ---------------------------------------------------------------------------
# CLI: exit codes and report rendering
# ---------------------------------------------------------------------------


def test_main_ok_on_real_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert drift.main([]) == 0
    assert "OK" in capsys.readouterr().out


def test_main_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert drift.main(["--json"]) == 0
    out = capsys.readouterr().out
    assert '"status": "ok"' in out


def test_main_fails_and_lists_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _write(tmp_path, CANON, "good\n")
    _write(tmp_path, COPY, "bad\n")
    monkeypatch.setattr(drift, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(drift, "TRACKED_DUPLICATES", TRACKED)
    assert drift.main(["-v"]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "drift" in out


def test_main_reports_no_tracked(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(drift, "TRACKED_DUPLICATES", {})
    assert drift.main([]) == 0
    assert "no duplicated scripts tracked" in capsys.readouterr().out

#!/usr/bin/env python3
"""Tests for scripts/fix_loop.py — the inert, disabled auto-fix loop.

These prove the safety properties hold even though the loop cannot run: the scope
guard rejects every protected path, the loop refuses while disabled or unguarded,
escalation fires at max_cycles, and the verdict always comes from a clean re-eval.
"""

from __future__ import annotations

from pathlib import Path

import fix_loop
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

PROTECTED_WRITE_TARGETS = [
    "features.yaml",
    "config/eval.example.yaml",
    "src/eval_harness/gating/__init__.py",
    "src/eval_harness/scorers/__init__.py",
    "src/eval_harness/judges/__init__.py",
    "tests/test_engine.py",
    ".github/workflows/eval-harness-ci.yml",
    "scripts/validations/F_006.py",
]


# ---------------------------------------------------------------------------
# ScopeGuard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", PROTECTED_WRITE_TARGETS)
def test_scope_guard_rejects_protected_writes(target: str, tmp_path: Path) -> None:
    sg = fix_loop.ScopeGuard(root=tmp_path)
    with pytest.raises(fix_loop.ProtectedPathError):
        sg.assert_writable(target)
    with pytest.raises(fix_loop.ProtectedPathError):
        sg.write_text(target, "nope")


def test_scope_guard_allows_implementation_write(tmp_path: Path) -> None:
    sg = fix_loop.ScopeGuard(root=tmp_path)
    written = sg.write_text("src/eval_harness/engine.py", "ok = 1\n")
    assert written.read_text(encoding="utf-8") == "ok = 1\n"


def test_scope_guard_rejects_absolute_path_outside_root(tmp_path: Path) -> None:
    sg = fix_loop.ScopeGuard(root=tmp_path)
    with pytest.raises(fix_loop.ProtectedPathError):
        sg.assert_writable("/etc/passwd")


def test_scope_guard_rejects_absolute_path_even_inside_root(tmp_path: Path) -> None:
    # Absolute addressing is rejected outright, even for a path under root.
    sg = fix_loop.ScopeGuard(root=tmp_path)
    with pytest.raises(fix_loop.ProtectedPathError):
        sg.assert_writable(str(tmp_path / "src" / "eval_harness" / "engine.py"))


def test_scope_guard_rejects_parent_traversal(tmp_path: Path) -> None:
    sg = fix_loop.ScopeGuard(root=tmp_path / "project")
    (tmp_path / "project").mkdir()
    with pytest.raises(fix_loop.ProtectedPathError):
        sg.write_text("../../etc/passwd", "nope")


def test_main_reports_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    assert fix_loop.main() == 0
    assert "DISABLED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Loop refusal / preconditions
# ---------------------------------------------------------------------------


def test_loop_refuses_when_disabled() -> None:
    with pytest.raises(fix_loop.FixLoopDisabledError):
        fix_loop.run_fix_loop(
            evaluate=lambda: False,
            apply_fix=lambda guard, cycle: None,
        )


def test_loop_refuses_when_guard_missing(tmp_path: Path) -> None:
    # Enabled, but the Phase-2 guard is absent in this empty root.
    with pytest.raises(fix_loop.FixLoopDisabledError):
        fix_loop.run_fix_loop(
            evaluate=lambda: False,
            apply_fix=lambda guard, cycle: None,
            enabled=True,
            root=tmp_path,
        )


def test_module_default_is_disabled() -> None:
    assert fix_loop.FIX_ENABLED is False


# ---------------------------------------------------------------------------
# Loop behaviour (enabled, against the real repo root where the guard exists)
# ---------------------------------------------------------------------------


def test_loop_already_passing_skips_fix() -> None:
    calls = []
    outcome = fix_loop.run_fix_loop(
        evaluate=lambda: True,
        apply_fix=lambda guard, cycle: calls.append(cycle),
        enabled=True,
        root=REPO_ROOT,
    )
    assert outcome.passed is True
    assert outcome.cycles == 0
    assert calls == []


def test_loop_verdict_from_clean_reeval() -> None:
    state = {"verdicts": [False, True]}

    def evaluate() -> bool:
        return state["verdicts"].pop(0)

    fixes = []
    outcome = fix_loop.run_fix_loop(
        evaluate=evaluate,
        apply_fix=lambda guard, cycle: fixes.append(cycle),
        enabled=True,
        root=REPO_ROOT,
    )
    assert outcome.passed is True
    assert outcome.cycles == 1
    assert fixes == [1]


def test_loop_escalates_on_exhaustion() -> None:
    fixes = []
    with pytest.raises(fix_loop.FixLoopExhaustedError):
        fix_loop.run_fix_loop(
            evaluate=lambda: False,
            apply_fix=lambda guard, cycle: fixes.append(cycle),
            enabled=True,
            root=REPO_ROOT,
            max_cycles=3,
        )
    assert fixes == [1, 2, 3]


def test_loop_rejects_bad_max_cycles() -> None:
    with pytest.raises(ValueError):
        fix_loop.run_fix_loop(
            evaluate=lambda: False,
            apply_fix=lambda guard, cycle: None,
            enabled=True,
            root=REPO_ROOT,
            max_cycles=0,
        )

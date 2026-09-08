"""Unit tests for scripts/run_tiered_tests.py.

Verifies tier selection, failure classification, platform command dispatch,
exit code 78 (EX_CONFIG) handling, fail-fast step reconciliation, and report generation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from run_tiered_tests import (
    StepResult,
    StepSpec,
    TriageReport,
    classify_failure,
    get_tier_steps,
    main,
    run_step,
    write_report,
)


def test_classify_failure() -> None:
    assert classify_failure("ModuleNotFoundError: No module named 'foo'") == "CAT-ENV"
    assert classify_failure("ImportError: cannot import name 'bar'") == "CAT-ENV"
    assert classify_failure("File exceeds the 500-line size budget") == "CAT-INVAR"
    assert classify_failure("charter-drift detected in CHARTER.md") == "CAT-INVAR"
    assert classify_failure("Matrix coverage artifact is stale") == "CAT-INVAR"
    assert classify_failure("ConnectionError: failed to reach api.langfuse.com") == "CAT-LIVE"
    assert classify_failure("Request timeout after 30s") == "CAT-LIVE"
    assert classify_failure("Rate limit reached: 429 Too Many Requests") == "CAT-LIVE"
    assert classify_failure("AssertionError: 4 != 5") == "CAT-LOGIC"
    assert classify_failure("Test execution failed: exit code 1") == "CAT-LOGIC"
    assert classify_failure("Random unrecognized message") == "CAT-UNKNOWN"


@pytest.mark.parametrize(
    ("tier_alias", "expected_prefix"),
    [
        ("fast", "TIER-1"),
        ("1", "TIER-1"),
        ("no-mock", "TIER-1"),
        ("integration", "TIER-2"),
        ("2", "TIER-2"),
        ("mock", "TIER-2"),
        ("full", "TIER-3"),
        ("3", "TIER-3"),
        ("e2e", "TIER-3"),
        ("live", "TIER-4"),
        ("4", "TIER-4"),
    ],
)
def test_get_tier_steps_aliases(tier_alias: str, expected_prefix: str) -> None:
    steps = get_tier_steps(tier_alias, sys.executable)
    assert len(steps) > 0
    for s in steps:
        assert s.tier.startswith(expected_prefix)


def test_get_tier_steps_all() -> None:
    steps = get_tier_steps("all", sys.executable)
    tiers_present = {s.tier.split()[0] for s in steps}
    assert tiers_present == {"TIER-1", "TIER-2", "TIER-3", "TIER-4"}


def test_get_tier_steps_platform_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows platform dispatch
    monkeypatch.setattr(sys, "platform", "win32")
    win_steps = get_tier_steps("full", sys.executable)
    e2e_win = next(s for s in win_steps if "All E2E Journeys" in s.name)
    assert e2e_win.command[0] == "powershell"
    assert "scripts/run_all_e2e.ps1" in e2e_win.command

    # POSIX platform dispatch
    monkeypatch.setattr(sys, "platform", "linux")
    linux_steps = get_tier_steps("full", sys.executable)
    e2e_linux = next(s for s in linux_steps if "All E2E Journeys" in s.name)
    assert e2e_linux.command[0] == "bash"
    assert "scripts/run_all_e2e.sh" in e2e_linux.command


def test_run_step_success() -> None:
    spec = StepSpec("TIER-1", "Echo Test", [sys.executable, "-c", "print('hello')"])
    res = run_step(spec)
    assert res.status == "PASS"
    assert "hello" in res.stdout
    assert res.duration_ms >= 0


def test_run_step_skip_ex_config(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_proc = MagicMock(returncode=78, stdout="", stderr="Not configured")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)
    spec = StepSpec("TIER-4", "Unconfigured Live Smoke", ["some_command"])
    res = run_step(spec)
    assert res.status == "SKIP"
    assert res.category is None


def test_run_step_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_proc = MagicMock(returncode=1, stdout="", stderr="AssertionError: values do not match")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_proc)
    spec = StepSpec("TIER-1", "Failing Assert", ["some_command"])
    res = run_step(spec)
    assert res.status == "FAIL"
    assert res.category == "CAT-LOGIC"
    assert "AssertionError" in res.error_signature


def test_run_step_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="mock_cmd", timeout=5)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    spec = StepSpec("TIER-4", "Hanging Service", ["mock_cmd"], timeout_sec=5)
    res = run_step(spec)
    assert res.status == "FAIL"
    assert res.category == "CAT-LIVE"
    assert "Timeout after 5s" in res.error_signature


def test_write_report(tmp_path: Path) -> None:
    report = TriageReport(
        timestamp="2026-09-08 12:00:00 UTC",
        total_steps=3,
        passed=1,
        failed=1,
        skipped=1,
        results=[
            StepResult("TIER-1", "Step 1", ["cmd1"], "PASS", 50),
            StepResult(
                "TIER-2",
                "Step 2",
                ["cmd2"],
                "FAIL",
                120,
                category="CAT-LOGIC",
                error_signature="AssertionError: 1 != 2",
                stdout="running...",
                stderr="AssertionError: 1 != 2",
            ),
            StepResult("TIER-4", "Step 3", ["cmd3"], "SKIP", 10),
        ],
    )
    write_report(report, tmp_path)

    json_file = tmp_path / "triage-report.json"
    md_file = tmp_path / "triage-report.md"
    assert json_file.exists()
    assert md_file.exists()

    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["total_steps"] == 3
    assert data["passed"] == 1
    assert data["failed"] == 1
    assert data["skipped"] == 1

    md_content = md_file.read_text(encoding="utf-8")
    assert "# Tiered Test & Triage Report" in md_content
    assert "AssertionError: 1 != 2" in md_content
    assert "| TIER-1 | Step 1 | **PASS** |" in md_content


def test_main_fail_fast_reconciliation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that when --fail-fast halts execution on error, remaining steps are marked SKIP."""
    step_calls = 0

    def mock_run_step(spec: StepSpec) -> StepResult:
        nonlocal step_calls
        step_calls += 1
        if step_calls == 1:
            return StepResult(spec.tier, spec.name, spec.command, "PASS", 10)
        if step_calls == 2:
            return StepResult(spec.tier, spec.name, spec.command, "FAIL", 20, category="CAT-LOGIC")
        return StepResult(spec.tier, spec.name, spec.command, "PASS", 10)

    monkeypatch.setattr("run_tiered_tests.run_step", mock_run_step)
    monkeypatch.setattr("run_tiered_tests.REPO_ROOT", tmp_path)

    # Run with --tier fast --fail-fast
    exit_code = main() if "--fail-fast" in sys.argv else 0
    # Direct test of main invocation
    test_args = ["run_tiered_tests.py", "--tier", "fast", "--fail-fast"]
    monkeypatch.setattr(sys, "argv", test_args)

    exit_code = main()
    assert exit_code == 1

    report_path = tmp_path / "artifacts" / "triage-report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))

    # Crucial invariant: passed + failed + skipped MUST equal total_steps
    assert data["passed"] == 1
    assert data["failed"] == 1
    assert data["skipped"] == data["total_steps"] - 2
    assert data["passed"] + data["failed"] + data["skipped"] == data["total_steps"]

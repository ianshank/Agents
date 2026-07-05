"""Tests for the shared fail-safe subprocess runner."""

from __future__ import annotations

import subprocess
import sys

from agent_core.subprocess_util import RC_NOT_FOUND, RC_TIMED_OUT, run_failsafe


def test_success_returns_completed_process() -> None:
    proc = run_failsafe([sys.executable, "-c", "print('hi')"], timeout=10)
    assert proc.returncode == 0
    assert "hi" in proc.stdout


def test_missing_binary_returns_not_found_code() -> None:
    proc = run_failsafe(["agent-core-nonexistent-binary-xyz"], timeout=5)
    assert proc.returncode == RC_NOT_FOUND
    assert isinstance(proc, subprocess.CompletedProcess)


def test_timeout_returns_timed_out_code() -> None:
    proc = run_failsafe([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    assert proc.returncode == RC_TIMED_OUT


def test_input_text_is_forwarded_to_stdin() -> None:
    proc = run_failsafe(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        timeout=10,
        input_text="payload",
    )
    assert proc.returncode == 0
    assert proc.stdout == "payload"

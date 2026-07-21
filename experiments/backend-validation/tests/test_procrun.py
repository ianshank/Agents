"""Unit tests for the injectable subprocess runner (the package's only subprocess seam)."""

from __future__ import annotations

import sys

from backend_validation.procrun import SubprocessRunner


def test_ok_command_captures_stdout() -> None:
    result = SubprocessRunner().run([sys.executable, "-c", "print('hello')"])
    assert result.ok and result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_nonzero_exit_is_data_not_an_exception() -> None:
    result = SubprocessRunner().run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert not result.ok and result.returncode == 3 and not result.timed_out


def test_timeout_is_reported_not_raised() -> None:
    # The child would sleep 5s but the 0.2s timeout kills it, so this stays fast.
    result = SubprocessRunner().run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    assert result.timed_out and not result.ok


def test_missing_binary_is_reported_not_raised() -> None:
    result = SubprocessRunner().run(["definitely-not-a-real-binary-bv"])
    assert not result.ok and result.returncode == -1
    assert result.stderr

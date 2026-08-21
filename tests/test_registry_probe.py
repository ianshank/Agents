import subprocess

import pytest

from tests._registry_probe import PROBE_TIMEOUT_SECONDS, run_probe


class _FakeCompletedProcess:
    """Minimal stand-in for subprocess.CompletedProcess used by the tests below."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_probe_failure_modes_are_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing probe raises with both stdout and stderr, not silence."""
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _FakeCompletedProcess(returncode=3, stderr="boom"))
    with pytest.raises(RuntimeError, match="exit 3") as exc_info:
        run_probe(["-c", "print('hi')"])
    assert "boom" in str(exc_info.value)

    def _timeout(*args: object, **kwargs: object) -> _FakeCompletedProcess:
        raise subprocess.TimeoutExpired(cmd="probe", timeout=PROBE_TIMEOUT_SECONDS, output="partial out")

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(RuntimeError, match="did not finish") as exc_info:
        run_probe(["-c", "print('hi')"])
    assert "partial out" in str(exc_info.value)


def test_probe_that_cannot_start_is_translated_not_leaked(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unusable interpreter must fail as a test failure, not a collection error."""

    def _boom(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("Exec format error")

    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(RuntimeError, match="could not start"):
        run_probe(["-c", "print('hi')"])

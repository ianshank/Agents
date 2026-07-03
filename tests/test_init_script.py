#!/usr/bin/env python3
"""Tests for scripts/init.py — cross-platform project initialisation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import init as init_script
import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_project_root_is_repo_root() -> None:
    root = init_script._project_root()
    assert (root / "scripts" / "init.py").exists()
    assert (root / "pyproject.toml").exists()


def test_venv_python_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(init_script.platform, "system", lambda: "Linux")
    assert init_script._venv_python(tmp_path) == tmp_path / "bin" / "python"
    monkeypatch.setattr(init_script.platform, "system", lambda: "Windows")
    assert init_script._venv_python(tmp_path) == tmp_path / "Scripts" / "python.exe"


def test_activate_hint_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(init_script.platform, "system", lambda: "Linux")
    assert init_script._activate_hint(tmp_path).startswith("source ")
    monkeypatch.setattr(init_script.platform, "system", lambda: "Windows")
    assert init_script._activate_hint(tmp_path).endswith("activate.bat")


# ---------------------------------------------------------------------------
# venv creation
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_create_venv_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    python = init_script._venv_python(venv)
    python.parent.mkdir(parents=True)
    python.touch()

    def _boom(*a: Any, **k: Any) -> _Result:
        raise AssertionError("subprocess must not run when the venv already exists")

    monkeypatch.setattr(init_script.subprocess, "run", _boom)
    assert init_script._create_venv(venv) is True


def test_create_venv_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **kw: Any) -> _Result:
        calls.append(cmd)
        return _Result(0)

    monkeypatch.setattr(init_script.subprocess, "run", _fake_run)
    assert init_script._create_venv(tmp_path / ".venv") is True
    assert calls and calls[0][1:3] == ["-m", "venv"]

    monkeypatch.setattr(init_script.subprocess, "run", lambda *a, **k: _Result(1, "no venv module"))
    assert init_script._create_venv(tmp_path / "other") is False


# ---------------------------------------------------------------------------
# Dependency install
# ---------------------------------------------------------------------------


def test_install_deps_uses_venv_pip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def _fake_run(cmd: list[str], **kw: Any) -> _Result:
        seen["cmd"] = cmd
        seen["cwd"] = kw.get("cwd")
        return _Result(0)

    monkeypatch.setattr(init_script.subprocess, "run", _fake_run)
    assert init_script._install_deps(tmp_path / ".venv", tmp_path) is True
    assert seen["cwd"] == str(tmp_path)
    assert seen["cmd"][0] == str(init_script._venv_python(tmp_path / ".venv"))
    assert init_script.INSTALL_EXTRAS in seen["cmd"]


def test_install_deps_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(init_script.subprocess, "run", lambda *a, **k: _Result(1, "resolver error"))
    assert init_script._install_deps(tmp_path / ".venv", tmp_path) is False


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def test_main_happy_path(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(init_script, "_create_venv", lambda venv: True)
    monkeypatch.setattr(init_script, "_install_deps", lambda venv, root: True)
    assert init_script.main([]) == 0
    assert "baseline ready" in capsys.readouterr().out


def test_main_venv_failure_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_script, "_create_venv", lambda venv: False)

    def _boom(*a: Any, **k: Any) -> bool:
        raise AssertionError("install must not run when venv creation failed")

    monkeypatch.setattr(init_script, "_install_deps", _boom)
    assert init_script.main([]) == 1


def test_main_install_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_script, "_create_venv", lambda venv: True)
    monkeypatch.setattr(init_script, "_install_deps", lambda venv, root: False)
    assert init_script.main([]) == 1


def test_module_is_runnable_directly() -> None:
    # The script must stay executable as `python scripts/init.py --help`-less
    # direct invocation; a no-op arg run would create a venv, so only assert
    # the module compiles standalone (import side effects already covered).
    src = Path(init_script.__file__).read_text(encoding="utf-8")
    compile(src, init_script.__file__, "exec")
    assert 'if __name__ == "__main__":' in src

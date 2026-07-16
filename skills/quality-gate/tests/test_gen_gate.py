"""Tests for the ``gen_gate`` runner, including real execution of the generated gate."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import gen_gate
import pytest

BASH = shutil.which("bash")


def _project(root: Path, *, broken: bool = False) -> None:
    """Write a minimal project the generated gate can actually run against."""
    (root / "src" / "demo").mkdir(parents=True)
    (root / "tests").mkdir()
    init = "import os\n" if broken else '"""demo."""\n'  # unused import -> ruff F401 when broken
    (root / "src" / "demo" / "__init__.py").write_text(init, encoding="utf-8")
    (root / "tests" / "test_ok.py").write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="demo"\nversion="0"\n'
        "[tool.ruff]\n[tool.mypy]\n[tool.pytest.ini_options]\ntestpaths=['tests']\n"
        '[tool.coverage.run]\nsource=["demo"]\n[tool.coverage.report]\nfail_under=0\n',
        encoding="utf-8",
    )


def test_stdout_mode_writes_nothing(tmp_path, capsys) -> None:
    _project(tmp_path)
    assert gen_gate.main(["--root", str(tmp_path), "--stdout"]) == 0
    assert "set -euo pipefail" in capsys.readouterr().out
    assert not (tmp_path / "scripts" / "quality-gate.sh").exists()


def test_default_write_is_executable(tmp_path) -> None:
    _project(tmp_path)
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    out = tmp_path / "scripts" / "quality-gate.sh"
    assert out.is_file()
    assert os.access(out, os.X_OK)


def test_print_ci(tmp_path, capsys) -> None:
    assert gen_gate.main(["--root", str(tmp_path), "--print-ci"]) == 0
    assert "./scripts/quality-gate.sh all" in capsys.readouterr().out


def test_no_op_gate_warns(tmp_path, capsys) -> None:
    assert gen_gate.main(["--root", str(tmp_path)]) == 0  # empty project
    assert "no checks detected" in capsys.readouterr().err


def test_check_up_to_date_drift_and_missing(tmp_path) -> None:
    _project(tmp_path)
    out = tmp_path / "scripts" / "quality-gate.sh"
    assert gen_gate.main(["--root", str(tmp_path), "--check"]) == 1  # missing
    gen_gate.main(["--root", str(tmp_path)])
    assert gen_gate.main(["--root", str(tmp_path), "--check"]) == 0  # fresh
    out.write_text("stale\n", encoding="utf-8")
    assert gen_gate.main(["--root", str(tmp_path), "--check"]) == 1  # drift


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_generated_script_passes_bash_syntax(tmp_path) -> None:
    _project(tmp_path)
    gen_gate.main(["--root", str(tmp_path)])
    out = tmp_path / "scripts" / "quality-gate.sh"
    assert subprocess.run([BASH, "-n", str(out)]).returncode == 0
    if shutil.which("shellcheck"):
        proc = subprocess.run(["shellcheck", str(out)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout


def _run_gate(root: Path, arg: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHON": "python3"}
    return subprocess.run(
        [BASH, "scripts/quality-gate.sh", arg],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_clean_project_passes_the_gate(tmp_path) -> None:
    _project(tmp_path, broken=False)
    gen_gate.main(["--root", str(tmp_path)])
    result = _run_gate(tmp_path, "all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_broken_project_fails_the_gate(tmp_path) -> None:
    _project(tmp_path, broken=True)
    gen_gate.main(["--root", str(tmp_path)])
    result = _run_gate(tmp_path, "lint")  # the unused import trips ruff
    assert result.returncode != 0


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_unknown_subcommand_is_usage_error(tmp_path) -> None:
    _project(tmp_path)
    gen_gate.main(["--root", str(tmp_path)])
    assert _run_gate(tmp_path, "bogus").returncode == 2

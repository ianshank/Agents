"""Tests for the ``gen_makefile`` runner, including real ``make`` parsing of the output."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import gen_makefile
import pytest


def _pip_src(root: Path) -> None:
    (root / "src" / "demo").mkdir(parents=True)
    (root / "src" / "demo" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires=["setuptools"]\n'
        '[project]\nname="demo"\nversion="0"\n'
        '[project.optional-dependencies]\ndev=["pytest","ruff","mypy","pytest-cov"]\n'
        "[tool.ruff]\n[tool.mypy]\n[tool.pytest.ini_options]\n"
        '[tool.coverage.run]\nsource=["demo"]\n[tool.coverage.report]\nfail_under=90\n',
        encoding="utf-8",
    )


def test_stdout_mode_prints_and_writes_nothing(tmp_path, capsys) -> None:
    _pip_src(tmp_path)
    rc = gen_makefile.main(["--root", str(tmp_path), "--stdout"])
    assert rc == 0
    out = capsys.readouterr().out
    assert ".DEFAULT_GOAL := help" in out
    assert not (tmp_path / "Makefile").exists()


def test_default_write_creates_makefile(tmp_path, capsys) -> None:
    _pip_src(tmp_path)
    rc = gen_makefile.main(["--root", str(tmp_path)])
    assert rc == 0
    assert "wrote" in capsys.readouterr().out
    assert (tmp_path / "Makefile").is_file()


def test_out_path_creates_nested_dirs(tmp_path) -> None:
    _pip_src(tmp_path)
    out = tmp_path / "nested" / "deep" / "Makefile"
    rc = gen_makefile.main(["--root", str(tmp_path), "--out", str(out)])
    assert rc == 0 and out.is_file()
    assert out.read_text(encoding="utf-8").endswith("\n")


def test_check_up_to_date(tmp_path) -> None:
    _pip_src(tmp_path)
    out = tmp_path / "Makefile"
    gen_makefile.main(["--root", str(tmp_path), "--out", str(out)])
    rc = gen_makefile.main(["--root", str(tmp_path), "--out", str(out), "--check"])
    assert rc == 0


def test_check_reports_drift(tmp_path) -> None:
    _pip_src(tmp_path)
    out = tmp_path / "Makefile"
    out.write_text("stale contents\n", encoding="utf-8")
    rc = gen_makefile.main(["--root", str(tmp_path), "--out", str(out), "--check"])
    assert rc == 1


def test_check_missing_file(tmp_path) -> None:
    _pip_src(tmp_path)
    rc = gen_makefile.main(["--root", str(tmp_path), "--out", str(tmp_path / "Makefile"), "--check"])
    assert rc == 1


@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_generated_makefile_parses_with_make(tmp_path) -> None:
    _pip_src(tmp_path)
    out = tmp_path / "Makefile"
    gen_makefile.main(["--root", str(tmp_path), "--out", str(out)])
    # `make -n` parses the file and resolves prerequisites without running recipes.
    for goal in ("help", "check", "clean"):
        proc = subprocess.run(
            ["make", "-f", str(out), "-n", goal],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert proc.returncode == 0, f"make -n {goal} failed: {proc.stderr}"

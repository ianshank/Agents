"""Tests for the ``gen_makefile`` runner, including real ``make`` parsing of the output."""

from __future__ import annotations

import logging
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


def test_verbose_logs_detected_facts(tmp_path, caplog) -> None:
    _pip_src(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="makegen"):
        gen_makefile.main(["--root", str(tmp_path), "--stdout", "--verbose"])
    assert any("detected facts" in r.message for r in caplog.records)


# --------------------------------------------------------- 1.1.0: workspace mode
def _workspace(root: Path) -> None:
    """A monorepo: root project plus two members with their own toolchains."""
    _pip_src(root)
    for name in ("pkg-a", "pkg-b"):
        member = root / name
        (member / "tests").mkdir(parents=True)
        (member / "pyproject.toml").write_text(
            f'[project]\nname="{name}"\nversion="0"\n[tool.ruff]\n[tool.pytest.ini_options]\ntestpaths=["tests"]\n',
            encoding="utf-8",
        )
        (member / "tests" / "test_ok.py").write_text("def test_ok() -> None:\n    assert True\n", encoding="utf-8")


def test_workspace_emits_root_and_member_makefiles(tmp_path) -> None:
    _workspace(tmp_path)
    assert gen_makefile.main(["--root", str(tmp_path), "--workspace"]) == 0
    root_body = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "check-pkg-a:" in root_body and "check-pkg-b:" in root_body
    assert "$(MAKE) -C pkg-a install" in root_body  # member installs via its own target
    assert "# regenerate: python " in root_body and "--workspace" in root_body  # provenance
    for name in ("pkg-a", "pkg-b"):
        member_body = (tmp_path / name / "Makefile").read_text(encoding="utf-8")
        assert "lint:" in member_body and "check:" in member_body
        assert "check-" not in member_body  # members get the plain single-package render
        assert "# regenerate: python " in member_body  # members carry provenance too


def test_flagless_regen_over_workspace_makefile_warns(tmp_path, capsys) -> None:
    # Regenerating WITHOUT --workspace over a fan-out Makefile silently deleted check-all
    # before this guard; now it must warn loudly.
    _workspace(tmp_path)
    gen_makefile.main(["--root", str(tmp_path), "--workspace"])
    assert gen_makefile.main(["--root", str(tmp_path)]) == 0  # flag-less rewrite
    err = capsys.readouterr().err
    assert "drops them" in err and "--workspace" in err
    assert "check-all" not in (tmp_path / "Makefile").read_text(encoding="utf-8")


def test_workspace_check_iterates_all_artifacts(tmp_path) -> None:
    _workspace(tmp_path)
    args = ["--root", str(tmp_path), "--workspace"]
    assert gen_makefile.main([*args, "--check"]) == 1  # nothing written yet
    gen_makefile.main(args)
    assert gen_makefile.main([*args, "--check"]) == 0  # all fresh
    (tmp_path / "pkg-b" / "Makefile").write_text("stale\n", encoding="utf-8")
    assert gen_makefile.main([*args, "--check"]) == 1  # one stale member is drift


def test_uncheckable_member_gets_no_check_fanout(tmp_path) -> None:
    # Never fabricate: a member with nothing gate-able has no `check` target in its own
    # Makefile, so the root must not emit `$(MAKE) -C member check` for it.
    _workspace(tmp_path)
    bare = tmp_path / "bare-pkg"
    bare.mkdir()
    (bare / "pyproject.toml").write_text('[project]\nname="bare-pkg"\n', encoding="utf-8")
    gen_makefile.main(["--root", str(tmp_path), "--workspace"])
    root_body = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "check-bare-pkg" not in root_body
    assert "check-pkg-a:" in root_body  # gate-able members keep their fan-out
    assert "$(MAKE) -C bare-pkg install" in root_body  # install-all still covers everyone
    assert "$(MAKE) -C bare-pkg clean" in root_body  # so does clean-all
    member_body = (bare / "Makefile").read_text(encoding="utf-8")
    assert "check:" not in member_body  # consistent with the omission above


def test_symlinked_dir_is_not_a_member(tmp_path) -> None:
    _workspace(tmp_path)
    (tmp_path / "linked").symlink_to(tmp_path / "pkg-a", target_is_directory=True)
    gen_makefile.main(["--root", str(tmp_path), "--workspace"])
    root_body = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "check-linked" not in root_body and "-e ./linked" not in root_body


def test_workspace_warns_when_no_members(tmp_path, capsys) -> None:
    _pip_src(tmp_path)
    assert gen_makefile.main(["--root", str(tmp_path), "--workspace"]) == 0
    assert "no member packages" in capsys.readouterr().err


def test_workspace_flag_off_is_backwards_compatible(tmp_path) -> None:
    _workspace(tmp_path)
    gen_makefile.main(["--root", str(tmp_path)])  # no --workspace
    root_body = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "check-all" not in root_body
    assert not (tmp_path / "pkg-a" / "Makefile").exists()


@pytest.mark.slow  # real make -> ruff + pytest subprocesses; can exceed 5s in CI
@pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")
def test_workspace_check_all_runs_members_for_real(tmp_path) -> None:
    _workspace(tmp_path)
    gen_makefile.main(["--root", str(tmp_path), "--workspace"])
    # `make -n check-all` resolves root check + both member delegations without running.
    proc = subprocess.run(["make", "-n", "check-all"], capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    # Real run of one member target end-to-end (ruff + pytest inside pkg-a).
    proc = subprocess.run(["make", "check-pkg-a"], capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr


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

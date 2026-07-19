"""Tests for the ``gen_gate`` runner, including real execution of the generated gate."""

from __future__ import annotations

import logging
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
        '[project.optional-dependencies]\ndev=["pytest-cov"]\n'
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


def test_verbose_logs_detected_facts(tmp_path, caplog) -> None:
    _project(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="gategen"):
        gen_gate.main(["--root", str(tmp_path), "--stdout", "--verbose"])
    assert any("facts for" in r.message for r in caplog.records)


# --------------------------------------------------- 1.1.0: explicit path flags
def test_path_flags_render_multi_path_gate_with_provenance(tmp_path) -> None:
    _project(tmp_path)
    argv = [
        "--root",
        str(tmp_path),
        "--lint-path",
        "src",
        "--lint-path",
        "tests",
        "--typecheck-path",
        "src/demo",
        "--typecheck-path",
        "tests",
    ]
    assert gen_gate.main(argv) == 0
    body = (tmp_path / "scripts" / "quality-gate.sh").read_text(encoding="utf-8")
    assert '"$PYTHON" -m ruff check "src" "tests"' in body
    assert '"$PYTHON" -m mypy "src/demo"' in body and '"$PYTHON" -m mypy "tests"' in body
    # Program path is sys.argv[0] as invoked (pytest's own path in-process), so assert the
    # structure and args rather than a hardcoded program.
    assert "# regenerate: python " in body
    assert "--lint-path src --lint-path tests" in body


def test_provenance_includes_explicit_out(tmp_path) -> None:
    _project(tmp_path)
    out = tmp_path / "custom" / "gate.sh"
    assert gen_gate.main(["--root", str(tmp_path), "--out", str(out)]) == 0
    body = out.read_text(encoding="utf-8")
    assert "--out " in body  # re-running the comment writes to the same place


def test_typecheck_flag_ignored_without_checker(tmp_path, caplog) -> None:
    # Never fabricate: a --typecheck-path flag cannot conjure a typecheck step.
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="gategen"):
        gen_gate.main(["--root", str(tmp_path), "--typecheck-path", "src"])
    assert any("ignoring --typecheck-path" in r.message for r in caplog.records)
    body = (tmp_path / "scripts" / "quality-gate.sh").read_text(encoding="utf-8")
    assert "do_typecheck" not in body
    assert "--typecheck-path" not in body  # ignored flags never appear in provenance


def test_lint_flag_ignored_without_ruff(tmp_path, caplog) -> None:
    # Parity with --typecheck-path: no detected ruff -> warn, no lint step, no provenance lie.
    (tmp_path / "pyproject.toml").write_text("[tool.mypy]\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="gategen"):
        gen_gate.main(["--root", str(tmp_path), "--lint-path", "src"])
    assert any("ignoring --lint-path" in r.message for r in caplog.records)
    body = (tmp_path / "scripts" / "quality-gate.sh").read_text(encoding="utf-8")
    assert "do_lint" not in body
    assert "--lint-path" not in body


# ------------------------------------------- 1.1.0: hand-extension marker seam
def _extend_below_marker(out, extra: str) -> None:
    """Insert hand content where the seam comment directs: after the marker, BEFORE the
    final ``main "$@"`` dispatch line (definitions must parse before dispatch runs)."""
    text = out.read_text(encoding="utf-8")
    out.write_text(text.replace('main "$@"', extra.rstrip("\n") + '\n\nmain "$@"', 1), encoding="utf-8")


def test_rewrite_preserves_hand_tail(tmp_path) -> None:
    _project(tmp_path)
    gen_gate.main(["--root", str(tmp_path)])
    out = tmp_path / "scripts" / "quality-gate.sh"
    _extend_below_marker(out, "do_extra() {\n  echo custom-step\n}\n")
    assert gen_gate.main(["--root", str(tmp_path)]) == 0  # regenerate over it
    body = out.read_text(encoding="utf-8")
    assert "do_extra() {" in body and "echo custom-step" in body  # tail survived
    assert body.count('main "$@"') == 1  # default tail not duplicated


def test_check_ignores_tail_edits_but_flags_prefix_drift(tmp_path) -> None:
    _project(tmp_path)
    args = ["--root", str(tmp_path)]
    gen_gate.main(args)
    out = tmp_path / "scripts" / "quality-gate.sh"
    _extend_below_marker(out, "do_extra() {\n  true\n}\n")
    assert gen_gate.main([*args, "--check"]) == 0  # hand tail is not drift
    body = out.read_text(encoding="utf-8")
    out.write_text(body.replace("set -euo pipefail", "set -e"), encoding="utf-8")
    assert gen_gate.main([*args, "--check"]) == 1  # generated prefix drift IS drift


def test_check_flags_missing_dispatch_line(tmp_path, capsys) -> None:
    # A gate truncated at the marker defines every check and runs NONE (exit 0); --check
    # must not certify that state as 'up to date'.
    _project(tmp_path)
    args = ["--root", str(tmp_path)]
    gen_gate.main(args)
    out = tmp_path / "scripts" / "quality-gate.sh"
    body = out.read_text(encoding="utf-8")
    out.write_text(body.replace('main "$@"', ""), encoding="utf-8")
    assert gen_gate.main([*args, "--check"]) == 1
    assert "dispatch line is missing" in capsys.readouterr().out


def test_rewrite_over_premarker_artifact_warns(tmp_path, capsys) -> None:
    # 1.0.x artifacts have no marker seam; rewriting them must be loud, never silent.
    _project(tmp_path)
    out = tmp_path / "scripts" / "quality-gate.sh"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("#!/usr/bin/env bash\n# 1.0.x era gate\ndo_security() { true; }\n", encoding="utf-8")
    assert gen_gate.main(["--root", str(tmp_path)]) == 0
    assert "NOT preserved" in capsys.readouterr().err
    assert "do_security" not in out.read_text(encoding="utf-8")  # rewritten whole, as warned


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_do_extra_hook_runs_in_all(tmp_path) -> None:
    _project(tmp_path)
    gen_gate.main(["--root", str(tmp_path)])
    out = tmp_path / "scripts" / "quality-gate.sh"
    sentinel = tmp_path / "extra-ran.txt"
    _extend_below_marker(out, f'do_extra() {{\n  echo yes > "{sentinel.as_posix()}"\n}}\n')
    result = _run_gate(tmp_path, "all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.is_file()  # the hand-extension hook executed as part of `all`


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

"""Tests for the ``gen_deploy`` runner, including real execution of the safety rails."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import gen_deploy
import pytest

BASH = shutil.which("bash")


def _bash_works() -> bool:
    """Return True only when bash can execute a script at a native temp path.

    WSL bash resolves on ``shutil.which`` but cannot handle Windows-style
    paths (``C:\\Users\\…``), returning exit-code 127.  We probe with a real
    temp-file to catch that.

    Returns:
        True if bash can execute a temp script, False otherwise.
    """
    if BASH is None:
        return False
    import tempfile

    script: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w") as f:
            f.write("#!/usr/bin/env bash\necho ok\n")
            script = f.name
        result = subprocess.run([BASH, script], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
    finally:
        if script:
            Path(script).unlink(missing_ok=True)


BASH_OK = _bash_works()


def _gen(root: Path, **extra: str) -> Path:
    argv = ["--root", str(root), "--app", "mysvc", "--artifact", "reg/mysvc:1", "--health-url", "https://h/z"]
    for key, val in extra.items():
        argv += [f"--{key.replace('_', '-')}", val]
    gen_deploy.main(argv)
    return root / "scripts" / "deploy.sh"


def test_stdout_mode_writes_nothing(tmp_path, capsys) -> None:
    assert gen_deploy.main(["--root", str(tmp_path), "--stdout"]) == 0
    assert "set -euo pipefail" in capsys.readouterr().out
    assert not (tmp_path / "scripts" / "deploy.sh").exists()


def test_default_write_is_executable(tmp_path) -> None:
    out = _gen(tmp_path)
    assert out.is_file() and os.access(out, os.X_OK)


def test_custom_out_path(tmp_path) -> None:
    out = tmp_path / "ops" / "deploy.sh"
    assert gen_deploy.main(["--out", str(out), "--app", "x"]) == 0
    assert out.is_file()


def test_check_missing_fresh_and_drift(tmp_path) -> None:
    out = tmp_path / "scripts" / "deploy.sh"
    args = ["--root", str(tmp_path), "--app", "mysvc", "--artifact", "reg/mysvc:1", "--health-url", "https://h/z"]
    assert gen_deploy.main([*args, "--check"]) == 1  # missing
    gen_deploy.main(args)
    assert gen_deploy.main([*args, "--check"]) == 0  # fresh
    out.write_text("stale\n", encoding="utf-8")
    assert gen_deploy.main([*args, "--check"]) == 1  # drift


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_generated_script_bash_syntax_and_shellcheck(tmp_path) -> None:
    out = _gen(tmp_path)
    assert subprocess.run([BASH, "-n", str(out)]).returncode == 0
    if shutil.which("shellcheck"):
        proc = subprocess.run(["shellcheck", str(out)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout


def _run(out: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(out), *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_dry_run_makes_no_changes_and_exits_zero(tmp_path) -> None:
    out = _gen(tmp_path)
    for cmd in ("build", "release", "rollback", "health-check"):
        result = _run(out, "--dry-run", "--yes", cmd)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "DRY-RUN" in result.stdout


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_unconfigured_artifact_fails_fast(tmp_path) -> None:
    # Regenerate leaving the artifact as the default placeholder.
    gen_deploy.main(["--root", str(tmp_path), "--app", "mysvc"])
    out = tmp_path / "scripts" / "deploy.sh"
    assert _run(out, "--yes", "release").returncode != 0


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_confirmation_gate_aborts_without_yes(tmp_path) -> None:
    out = _gen(tmp_path)
    # Empty stdin -> no confirmation -> abort non-zero (no --yes, no --dry-run).
    assert _run(out, "release", stdin="").returncode != 0


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_confirmation_gate_proceeds_on_yes_reply(tmp_path) -> None:
    out = _gen(tmp_path)
    # Typing "y" passes the gate; the placeholder `true` commands then succeed.
    assert _run(out, "rollback", stdin="y\n").returncode == 0


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_unknown_subcommand_is_usage_error(tmp_path) -> None:
    out = _gen(tmp_path)
    assert _run(out, "bogus").returncode == 2
    assert _run(out).returncode == 2  # no subcommand


@pytest.mark.skipif(not BASH_OK, reason="bash not functional on this platform")
def test_shell_metacharacters_produce_valid_and_safe_script(tmp_path) -> None:
    # A value with $()/backticks must not break syntax or execute when ARTIFACT is unset.
    gen_deploy.main(
        ["--root", str(tmp_path), "--app", "svc", "--artifact", "x$(id)`whoami`", "--health-url", "https://h/z"]
    )
    out = tmp_path / "scripts" / "deploy.sh"
    assert subprocess.run([BASH, "-n", str(out)]).returncode == 0
    if shutil.which("shellcheck"):
        proc = subprocess.run(["shellcheck", str(out)], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout
    # Dry-run with ARTIFACT unset: the default expands to the LITERAL value, so nothing executes.
    result = _run(out, "--dry-run", "--yes", "build")
    assert result.returncode == 0
    assert "uid=" not in result.stdout  # `id` never ran


def test_verbose_logs_deploy_config(tmp_path, caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="deploygen"):
        gen_deploy.main(["--root", str(tmp_path), "--app", "svc", "--stdout", "--verbose"])
    assert any("deploy config" in r.message for r in caplog.records)

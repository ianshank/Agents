"""End-to-end hook tests: each hook runs as a subprocess with the real
stdin → stdout/exit-code contract, exactly as the harness invokes it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"


def run_hook(
    script: str,
    event: dict[str, Any] | str,
    env_overrides: dict[str, str] | None = None,
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    import os

    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    env.update(env_overrides or {})
    payload = event if isinstance(event, str) else json.dumps(event)
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
    )


def decision(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(proc.stdout)["hookSpecificOutput"]  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# pre_tool_guard — fail closed
# ---------------------------------------------------------------------------


def test_guard_denies_env_file_read() -> None:
    proc = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Read", "tool_input": {"file_path": "/repo/app/.env"}},
    )
    assert proc.returncode == 0
    out = decision(proc)
    assert out["permissionDecision"] == "deny"
    assert ".env" in out["permissionDecisionReason"]


def test_guard_allows_env_example_and_normal_files() -> None:
    for path in ("/repo/.env.example", "/repo/src/main.py"):
        proc = run_hook(
            "pre_tool_guard.py", {"tool_name": "Read", "tool_input": {"file_path": path}}
        )
        assert proc.returncode == 0 and proc.stdout.strip() == "", path


def test_guard_denies_extra_glob_from_env() -> None:
    proc = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Read", "tool_input": {"file_path": "/repo/deploy/vault.yaml"}},
        {"CLAUDE_FOUNDATION_GUARD_DENY_GLOBS": "**/vault.yaml,**/*.kdbx"},
    )
    assert decision(proc)["permissionDecision"] == "deny"


def test_guard_denies_bash_secret_reference() -> None:
    proc = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Bash", "tool_input": {"command": "cat .env | grep KEY"}},
    )
    assert decision(proc)["permissionDecision"] == "deny"
    ok = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Bash", "tool_input": {"command": "cat .env.example"}},
    )
    assert ok.stdout.strip() == ""


def test_guard_denies_write_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    scratch = tmp_path / "scratch"
    project.mkdir()
    scratch.mkdir()
    outside = tmp_path / "elsewhere" / "x.txt"
    # tmp_path itself lives under the system temp dir (the default scratch), so
    # pin the scratch allowance to a specific directory for this test.
    base_env = {
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_FOUNDATION_GUARD_SCRATCH_DIRS": str(scratch),
    }
    proc = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(outside)}},
        base_env,
    )
    assert decision(proc)["permissionDecision"] == "deny"

    inside = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(project / "ok.txt")}},
        base_env,
    )
    assert inside.stdout.strip() == ""

    scratch_ok = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(scratch / "notes.txt")}},
        base_env,
    )
    assert scratch_ok.stdout.strip() == ""

    default_scratch_ok = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "under-temp.txt")}},
        {"CLAUDE_PROJECT_DIR": str(project)},
    )
    assert default_scratch_ok.stdout.strip() == ""

    override = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(outside)}},
        {**base_env, "CLAUDE_FOUNDATION_GUARD_ALLOW_OUTSIDE": "1"},
    )
    assert override.stdout.strip() == ""


def test_guard_reads_outside_project_are_allowed(tmp_path: Path) -> None:
    proc = run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "anywhere.txt")}},
        {"CLAUDE_PROJECT_DIR": str(tmp_path / "project")},
    )
    assert proc.stdout.strip() == ""


def test_guard_fails_closed_on_malformed_input() -> None:
    proc = run_hook("pre_tool_guard.py", "this is not json")
    assert proc.returncode == 2
    assert "failing closed" in proc.stderr


def test_guard_writes_audit_log(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    run_hook(
        "pre_tool_guard.py",
        {"tool_name": "Read", "tool_input": {"file_path": "/repo/.env"}},
        {"CLAUDE_FOUNDATION_LOG_DIR": str(log_dir)},
    )
    record = json.loads((log_dir / "pre-tool-guard.jsonl").read_text().splitlines()[0])
    assert record["event"] == "deny" and record["hook"] == "pre-tool-guard"


# ---------------------------------------------------------------------------
# post_edit_verify — fail open
# ---------------------------------------------------------------------------


def test_verify_noop_without_config(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n", encoding="utf-8")
    proc = run_hook(
        "post_edit_verify.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
    )
    assert proc.returncode == 0 and proc.stdout.strip() == ""


def test_verify_clean_file_emits_nothing(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n", encoding="utf-8")
    proc = run_hook(
        "post_edit_verify.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
        {"CLAUDE_FOUNDATION_VERIFY_CMD": f'"{sys.executable}" -c "import sys; sys.exit(0)"'},
    )
    assert proc.returncode == 0 and proc.stdout.strip() == ""


def test_verify_failure_becomes_additional_context(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n", encoding="utf-8")
    checker = tmp_path / "checker.py"
    checker.write_text(
        "import sys\nprint('finding: bad style in', sys.argv[1])\nsys.exit(1)\n",
        encoding="utf-8",
    )
    proc = run_hook(
        "post_edit_verify.py",
        {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
        {"CLAUDE_FOUNDATION_VERIFY_CMD": f'"{sys.executable}" "{checker}" {{file}}'},
    )
    assert proc.returncode == 0
    context = decision(proc)["additionalContext"]
    assert "finding: bad style" in context and str(target) in context


def test_verify_fails_open_on_bad_command_and_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "f.py"
    target.write_text("x = 1\n", encoding="utf-8")
    broken = run_hook(
        "post_edit_verify.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
        {"CLAUDE_FOUNDATION_VERIFY_CMD": "definitely-not-a-real-binary {file}"},
    )
    assert broken.returncode == 0 and "skipped" in broken.stderr

    missing = run_hook(
        "post_edit_verify.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "ghost.py")}},
        {"CLAUDE_FOUNDATION_VERIFY_CMD": "echo {file}"},
    )
    assert missing.returncode == 0 and missing.stdout.strip() == ""


def test_verify_fails_open_on_malformed_input() -> None:
    proc = run_hook("post_edit_verify.py", "not json", {"CLAUDE_FOUNDATION_VERIFY_CMD": "echo hi"})
    assert proc.returncode == 0 and "skipped" in proc.stderr


# ---------------------------------------------------------------------------
# session_logger — fail open, privacy-conscious
# ---------------------------------------------------------------------------


def test_logger_noop_without_log_dir() -> None:
    proc = run_hook(
        "session_logger.py",
        {"tool_name": "Read", "tool_input": {"file_path": "/x"}, "session_id": "s1"},
    )
    assert proc.returncode == 0 and proc.stdout.strip() == ""


def test_logger_records_shape_not_values(tmp_path: Path) -> None:
    log_dir = tmp_path / "audit"
    secret = "super-secret-value-do-not-log"
    proc = run_hook(
        "session_logger.py",
        {
            "tool_name": "Bash",
            "tool_input": {"command": secret},
            "session_id": "s1",
        },
        {"CLAUDE_FOUNDATION_LOG_DIR": str(log_dir)},
    )
    assert proc.returncode == 0
    raw = (log_dir / "session-logger.jsonl").read_text()
    record = json.loads(raw.splitlines()[0])
    assert record["tool"] == "Bash" and record["session_id"] == "s1"
    assert record["input_shape"] == {"command": len(secret)}
    assert secret not in raw


def test_logger_fails_open_on_malformed_input(tmp_path: Path) -> None:
    proc = run_hook("session_logger.py", "not json", {"CLAUDE_FOUNDATION_LOG_DIR": str(tmp_path)})
    assert proc.returncode == 0 and "skipped" in proc.stderr

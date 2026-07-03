"""In-process hook unit tests (branch coverage; the stdin/exit contract is
covered end-to-end in test_hooks_e2e.py)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

import _lib
import post_edit_verify
import pre_tool_guard
import session_logger


def _event(tool: str, **tool_input: Any) -> dict[str, Any]:
    return {"tool_name": tool, "tool_input": tool_input}


# ---------------------------------------------------------------------------
# _lib
# ---------------------------------------------------------------------------


def test_read_event_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        _lib.read_event(io.StringIO("[1, 2]"))
    assert _lib.read_event(io.StringIO('{"a": 1}')) == {"a": 1}


def test_deny_and_context_payload_shapes() -> None:
    out = io.StringIO()
    _lib.deny("PreToolUse", "nope", stream=out)
    payload = json.loads(out.getvalue())["hookSpecificOutput"]
    assert payload == {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "nope",
    }
    out = io.StringIO()
    _lib.allow_with_context("PostToolUse", "fyi", stream=out)
    assert json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"] == "fyi"


def test_log_event_noop_without_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_lib.LOG_DIR_ENV, raising=False)
    _lib.log_event("h", "e")  # must not raise or create anything
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setenv(_lib.LOG_DIR_ENV, str(tmp_path / "logs"))
    _lib.log_event("h", "e", detail=7)
    record = json.loads((tmp_path / "logs" / "h.jsonl").read_text())
    assert record["event"] == "e" and record["detail"] == 7


def test_log_event_swallows_fs_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not dir", encoding="utf-8")
    monkeypatch.setenv(_lib.LOG_DIR_ENV, str(blocker / "sub"))
    _lib.log_event("h", "e")  # must not raise


# ---------------------------------------------------------------------------
# pre_tool_guard.check
# ---------------------------------------------------------------------------


def test_check_ignores_unknown_tools_and_empty_paths() -> None:
    assert pre_tool_guard.check(_event("WebFetch", url="https://x")) is None
    assert pre_tool_guard.check(_event("Read")) is None
    assert pre_tool_guard.check({"tool_name": "Read"}) is None


def test_check_notebook_path_and_windows_separators() -> None:
    reason = pre_tool_guard.check(_event("NotebookEdit", notebook_path="C:\\repo\\.env"))
    assert reason is not None and ".env" in reason


def test_grep_and_glob_paths_are_guarded() -> None:
    assert pre_tool_guard.check(_event("Grep", path="/repo/.env")) is not None
    assert pre_tool_guard.check(_event("Glob", path="/repo/secrets/id_ed25519")) is not None
    assert pre_tool_guard.check(_event("Grep", path="/repo/src/main.py")) is None


@pytest.mark.parametrize(
    "name",
    ["prod.env", "production.env", "local.env", "id_ed25519", "id_ecdsa", "credentials", "app.pem"],
)
def test_extended_secret_names_are_blocked(name: str) -> None:
    assert pre_tool_guard.check(_event("Read", file_path=f"/repo/{name}")) is not None


def test_check_relative_write_inside_project_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(pre_tool_guard.PROJECT_DIR_ENV, str(tmp_path))
    assert pre_tool_guard.check(_event("Write", file_path="src/ok.py")) is None


def test_relative_traversal_write_is_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv(pre_tool_guard.PROJECT_DIR_ENV, str(project))
    monkeypatch.setenv(pre_tool_guard.SCRATCH_DIRS_ENV, str(tmp_path / "none"))
    # B1 regression: a relative "../" escape must be resolved and denied.
    assert pre_tool_guard.check(_event("Write", file_path="../escape.txt")) is not None
    assert pre_tool_guard.check(_event("Write", file_path="src/ok.py")) is None


def test_symlink_alias_read_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("SECRET=1\n", encoding="utf-8")
    link = project / "notes.txt"
    link.symlink_to(project / ".env")
    monkeypatch.setenv(pre_tool_guard.PROJECT_DIR_ENV, str(project))
    assert pre_tool_guard.check(_event("Read", file_path=str(link))) is not None


def test_non_string_path_fails_closed() -> None:
    with pytest.raises(ValueError, match="non-string"):
        pre_tool_guard.check(_event("Read", file_path=["/repo/.env"]))


def test_project_dir_falls_back_to_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(pre_tool_guard.PROJECT_DIR_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(pre_tool_guard.SCRATCH_DIRS_ENV, str(tmp_path / "none"))
    # m2 fix: with no CLAUDE_PROJECT_DIR, containment is enforced against cwd.
    assert pre_tool_guard.check(_event("Write", file_path="/somewhere/else.txt")) is not None
    assert pre_tool_guard.check(_event("Write", file_path=str(tmp_path / "in.txt"))) is None


def test_scratch_dirs_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(pre_tool_guard.SCRATCH_DIRS_ENV, raising=False)
    assert len(pre_tool_guard._scratch_dirs()) == 1
    monkeypatch.setenv(pre_tool_guard.SCRATCH_DIRS_ENV, f"{tmp_path / 'a'}, {tmp_path / 'b'}")
    assert pre_tool_guard._scratch_dirs() == (
        (tmp_path / "a").resolve(),
        (tmp_path / "b").resolve(),
    )
    monkeypatch.setenv(pre_tool_guard.SCRATCH_DIRS_ENV, "")
    assert pre_tool_guard._scratch_dirs() == ()


def test_guard_main_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_event("Read", file_path="/r/.env"))))
    assert pre_tool_guard.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert pre_tool_guard.main() == 2
    assert "failing closed" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# post_edit_verify
# ---------------------------------------------------------------------------


def test_build_command_substitutes_file_as_single_arg() -> None:
    cmd = post_edit_verify.build_command("ruff check {file}", "/p/with space.py")
    assert cmd == ["ruff", "check", "/p/with space.py"]


def test_verify_none_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(post_edit_verify.VERIFY_CMD_ENV, raising=False)
    assert post_edit_verify.verify(_event("Write", file_path="x")) is None
    monkeypatch.setenv(post_edit_verify.VERIFY_CMD_ENV, "echo {file}")
    assert post_edit_verify.verify(_event("Write", file_path=str(tmp_path / "ghost"))) is None
    assert post_edit_verify.verify(_event("Write")) is None


def test_verify_clean_and_failing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "t.py"
    target.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv(
        post_edit_verify.VERIFY_CMD_ENV, f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    )
    assert post_edit_verify.verify(_event("Edit", file_path=str(target))) is None

    checker = tmp_path / "c.py"
    checker.write_text("import sys\nprint('bad thing')\nsys.exit(3)\n", encoding="utf-8")
    monkeypatch.setenv(post_edit_verify.VERIFY_CMD_ENV, f'"{sys.executable}" "{checker}" {{file}}')
    finding = post_edit_verify.verify(_event("Edit", file_path=str(target)))
    assert finding is not None and "bad thing" in finding and "exit 3" in finding


def test_verify_main_emits_context_and_fails_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "t.py"
    target.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv(
        post_edit_verify.VERIFY_CMD_ENV,
        f'"{sys.executable}" -c "import sys; print(\'oops\'); sys.exit(1)"',
    )
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps(_event("Write", file_path=str(target))))
    )
    assert post_edit_verify.main() == 0
    assert "oops" in json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]

    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert post_edit_verify.main() == 0
    assert "skipped" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# session_logger
# ---------------------------------------------------------------------------


def test_input_shape_maps_lengths_only() -> None:
    shape = session_logger.input_shape({"command": "secret!", "count": 12})
    assert shape == {"command": 7, "count": 2}


def test_logger_main_noop_and_record(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_lib.LOG_DIR_ENV, raising=False)
    assert session_logger.main() == 0  # no-op before reading stdin

    monkeypatch.setenv(_lib.LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({**_event("Read", file_path="/x"), "session_id": "s"})),
    )
    assert session_logger.main() == 0
    record = json.loads((tmp_path / "session-logger.jsonl").read_text())
    assert record["tool"] == "Read" and record["input_shape"] == {"file_path": 2}


def test_logger_main_fails_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(_lib.LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert session_logger.main() == 0
    assert "skipped" in capsys.readouterr().err

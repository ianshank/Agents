#!/usr/bin/env python3
"""PreToolUse guard — blocks secret-file reads and out-of-project writes.

Fail-CLOSED (ADR 0002): a matched rule denies via the documented JSON contract
(exit 0 + ``permissionDecision: "deny"``); an internal error denies via exit 2
with the reason on stderr. Security checks must not fail open.

Configuration (no hardcoded values beyond named defaults):
  CLAUDE_FOUNDATION_GUARD_DENY_GLOBS     extra comma-separated path globs to deny
  CLAUDE_FOUNDATION_GUARD_ALLOW_OUTSIDE  "1" disables the outside-project write denial
  CLAUDE_FOUNDATION_GUARD_SCRATCH_DIRS   comma-separated dirs writable outside the
                                         project (default: the system temp dir)
  CLAUDE_PROJECT_DIR                     project root (set by the harness)
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from _lib import deny, log_event, read_event

HOOK = "pre-tool-guard"
EVENT_NAME = "PreToolUse"

DENY_GLOBS_ENV = "CLAUDE_FOUNDATION_GUARD_DENY_GLOBS"
ALLOW_OUTSIDE_ENV = "CLAUDE_FOUNDATION_GUARD_ALLOW_OUTSIDE"
SCRATCH_DIRS_ENV = "CLAUDE_FOUNDATION_GUARD_SCRATCH_DIRS"
PROJECT_DIR_ENV = "CLAUDE_PROJECT_DIR"

# Secret-bearing files no tool call should read or write. ``.env.example`` is
# the documented exception (allowed).
DEFAULT_DENY_GLOBS: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/id_rsa*",
    "**/credentials",
    "**/credentials.json",
)
ALLOW_GLOBS: tuple[str, ...] = ("**/.env.example",)

_FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit"})
_WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
# Bash commands that mention a secret file by name (not .env.example).
_BASH_SECRET_RE = re.compile(r"(?<![\w.])\.env(?!\.example)(\.\w+)?\b|\bid_rsa\b|\.pem\b")


def _deny_globs() -> tuple[str, ...]:
    extra = tuple(g.strip() for g in os.environ.get(DENY_GLOBS_ENV, "").split(",") if g.strip())
    return DEFAULT_DENY_GLOBS + extra


def _scratch_dirs() -> tuple[Path, ...]:
    """Directories writable outside the project (default: the system temp dir)."""
    configured = os.environ.get(SCRATCH_DIRS_ENV)
    if configured is None:
        return (Path(tempfile.gettempdir()).resolve(),)
    return tuple(Path(d.strip()).resolve() for d in configured.split(",") if d.strip())


def _matches(path_str: str, globs: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path_str.replace("\\", "/"))
    as_posix = candidate.as_posix()
    # Match both the full path and the basename so bare names like ".env" hit.
    return any(
        fnmatch.fnmatch(as_posix, glob) or fnmatch.fnmatch(candidate.name, glob.rsplit("/", 1)[-1])
        for glob in globs
    )


def check(event: dict[str, Any]) -> str | None:
    """Return a denial reason, or None to allow."""
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}

    if tool in _FILE_TOOLS:
        path_str = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if path_str:
            if _matches(path_str, ALLOW_GLOBS):
                return None
            if _matches(path_str, _deny_globs()):
                return f"{tool} on secret-bearing path blocked by {HOOK}: {path_str}"
            if (
                tool in _WRITE_TOOLS
                and os.environ.get(ALLOW_OUTSIDE_ENV) != "1"
                and os.environ.get(PROJECT_DIR_ENV)
            ):
                project = Path(os.environ[PROJECT_DIR_ENV]).resolve()
                target = Path(path_str)
                if target.is_absolute():
                    resolved = target.resolve()
                    if not (
                        resolved.is_relative_to(project)
                        or any(resolved.is_relative_to(s) for s in _scratch_dirs())
                    ):
                        return (
                            f"{tool} outside the project directory blocked by {HOOK}: "
                            f"{resolved} (set {ALLOW_OUTSIDE_ENV}=1 to permit)"
                        )
    elif tool == "Bash":
        command = str(tool_input.get("command") or "")
        if _BASH_SECRET_RE.search(command):
            return f"Bash command references a secret-bearing file; blocked by {HOOK}"
    return None


def main() -> int:
    try:
        event = read_event()
        reason = check(event)
    except Exception as exc:  # fail closed: unknown state must not slip through
        log_event(HOOK, "internal-error", error=repr(exc))
        print(f"{HOOK}: internal error, failing closed: {exc}", file=sys.stderr)
        return 2
    if reason:
        log_event(HOOK, "deny", tool=event.get("tool_name"), reason=reason)
        deny(EVENT_NAME, reason)
    else:
        log_event(HOOK, "allow", tool=event.get("tool_name"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

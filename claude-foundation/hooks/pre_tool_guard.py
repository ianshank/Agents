#!/usr/bin/env python3
"""PreToolUse guard — blocks secret-file reads and out-of-project writes.

Fail-CLOSED (ADR 0002): a matched rule denies via the documented JSON contract
(exit 0 + ``permissionDecision: "deny"``); an internal error denies via exit 2
with the reason on stderr. Security checks must not fail open.

Coverage and its limits (be honest about the threat model):
  * File tools (Read/Edit/Write/NotebookEdit/Grep/Glob): the path — both as
    given and after resolving symlinks and ``..`` relative to the project — is
    matched against the secret-file deny globs; writes are additionally confined
    to the project and configured scratch dirs. This is the real barrier.
  * Bash: a best-effort substring/regex check over the raw command. The shell
    normalizes away quoting, wildcards, and encodings, so this is
    defense-in-depth only, NOT a guarantee — do not rely on it alone.
  * MCP file-reading servers are out of scope here; scope them at the MCP layer.

Configuration (no hardcoded values beyond named defaults):
  CLAUDE_FOUNDATION_GUARD_DENY_GLOBS     extra comma-separated path globs to deny
  CLAUDE_FOUNDATION_GUARD_ALLOW_OUTSIDE  "1" disables the outside-project write denial
  CLAUDE_FOUNDATION_GUARD_SCRATCH_DIRS   comma-separated dirs writable outside the
                                         project (default: the system temp dir)
  CLAUDE_PROJECT_DIR                     project root (falls back to cwd if unset)
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
    "**/*.env",
    "**/*.pem",
    "**/id_rsa*",
    "**/id_ed25519*",
    "**/id_ecdsa*",
    "**/credentials",
    "**/credentials.json",
)
ALLOW_GLOBS: tuple[str, ...] = ("**/.env.example", "**/*.env.example")

# Read-only file tools apply the secret-glob check; write tools add containment.
_READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
_WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
_FILE_TOOLS = _READ_TOOLS | _WRITE_TOOLS
_PATH_KEYS = ("file_path", "notebook_path", "path")
# Best-effort Bash barrier (see module docstring): any prefix + .env (except
# .env.example), private-key names, .pem, and credentials files.
_BASH_SECRET_RE = re.compile(
    r"\.env(?!\.example)|\.pem\b|\bid_(?:rsa|ed25519|ecdsa)\b|\bcredentials(?:\.json)?\b",
    re.IGNORECASE,
)


def _deny_globs() -> tuple[str, ...]:
    extra = tuple(g.strip() for g in os.environ.get(DENY_GLOBS_ENV, "").split(",") if g.strip())
    return DEFAULT_DENY_GLOBS + extra


def _project_dir() -> Path:
    return Path(os.environ.get(PROJECT_DIR_ENV) or os.getcwd()).resolve()


def _scratch_dirs() -> tuple[Path, ...]:
    """Directories writable outside the project (default: the system temp dir)."""
    configured = os.environ.get(SCRATCH_DIRS_ENV)
    if configured is None:
        return (Path(tempfile.gettempdir()).resolve(),)
    return tuple(Path(d.strip()).resolve() for d in configured.split(",") if d.strip())


def _resolve(path_str: str) -> Path:
    """Resolve ``path_str`` (relative → project-relative), following symlinks.

    ``resolve()`` works even when trailing components do not exist yet (writes).
    """
    target = Path(path_str)
    if not target.is_absolute():
        target = _project_dir() / target
    return target.resolve()


def _matches(path_str: str, globs: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path_str.replace("\\", "/"))
    as_posix = candidate.as_posix()
    # Match both the full path and the basename so bare names like ".env" hit.
    return any(
        fnmatch.fnmatch(as_posix, glob) or fnmatch.fnmatch(candidate.name, glob.rsplit("/", 1)[-1])
        for glob in globs
    )


def _is_secret_path(path_str: str, resolved: Path) -> bool:
    """True if the raw path OR its symlink-resolved target is a denied secret.

    A candidate is denied when it matches a deny glob and is not an allowed
    ``.env.example``. Checking the resolved target defeats symlink aliasing
    (e.g. ``notes.txt -> .env``); checking the raw path keeps bare names working.
    """
    deny_globs = _deny_globs()
    return any(
        _matches(candidate, deny_globs) and not _matches(candidate, ALLOW_GLOBS)
        for candidate in (path_str, resolved.as_posix())
    )


def _extract_path(tool_input: dict[str, Any]) -> str | None:
    """Return the path string, or raise ValueError for a non-string path value."""
    for key in _PATH_KEYS:
        if key in tool_input:
            value = tool_input[key]
            if value in (None, ""):
                continue
            if not isinstance(value, str):
                raise ValueError(f"non-string {key}: {value!r}")
            return value
    return None


def check(event: dict[str, Any]) -> str | None:
    """Return a denial reason, or None to allow."""
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}

    if tool in _FILE_TOOLS:
        path_str = _extract_path(tool_input)
        if not path_str:
            return None
        resolved = _resolve(path_str)
        if _is_secret_path(path_str, resolved):
            return f"{tool} on secret-bearing path blocked by {HOOK}: {path_str}"
        if tool in _WRITE_TOOLS and os.environ.get(ALLOW_OUTSIDE_ENV) != "1":
            project = _project_dir()
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

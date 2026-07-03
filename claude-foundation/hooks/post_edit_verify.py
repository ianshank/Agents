#!/usr/bin/env python3
"""PostToolUse verifier — lints/typechecks a just-edited file.

Fail-OPEN (ADR 0002): advisory only. Findings are returned to the model as
``additionalContext``; every path out of this script exits 0. A no-op unless
``CLAUDE_FOUNDATION_VERIFY_CMD`` is configured.

Configuration:
  CLAUDE_FOUNDATION_VERIFY_CMD      command template; ``{file}`` is replaced with
                                    the edited path (e.g. ``ruff check {file}``)
  CLAUDE_FOUNDATION_VERIFY_TIMEOUT  seconds before the check is abandoned (default 30)
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Any

from _lib import allow_with_context, log_event, read_event

HOOK = "post-edit-verify"
EVENT_NAME = "PostToolUse"

VERIFY_CMD_ENV = "CLAUDE_FOUNDATION_VERIFY_CMD"
VERIFY_TIMEOUT_ENV = "CLAUDE_FOUNDATION_VERIFY_TIMEOUT"
_DEFAULT_TIMEOUT_S = 30.0
_MAX_CONTEXT_LINES = 20


def build_command(template: str, file_path: str) -> list[str]:
    """Split the template and substitute ``{file}`` as a single argv element."""
    return [part.replace("{file}", file_path) for part in shlex.split(template)]


def verify(event: dict[str, Any]) -> str | None:
    """Run the configured check; return finding text or None when clean/no-op."""
    template = os.environ.get(VERIFY_CMD_ENV)
    if not template:
        return None
    tool_input = event.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    if not file_path or not os.path.exists(file_path):
        return None
    timeout = float(os.environ.get(VERIFY_TIMEOUT_ENV, _DEFAULT_TIMEOUT_S))
    result = subprocess.run(
        build_command(template, file_path),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    log_event(HOOK, "verified", file=file_path, returncode=result.returncode)
    if result.returncode == 0:
        return None
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-_MAX_CONTEXT_LINES:])
    return f"{HOOK}: check failed for {file_path} (exit {result.returncode}):\n{tail}"


def main() -> int:
    try:
        event = read_event()
        finding = verify(event)
        if finding:
            allow_with_context(EVENT_NAME, finding)
    except Exception as exc:  # fail open: advisory checks never block work
        log_event(HOOK, "internal-error", error=repr(exc))
        print(f"{HOOK}: skipped ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

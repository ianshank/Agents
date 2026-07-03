"""Shared helpers for foundation hooks.

Hooks execute inside arbitrary consumer environments, so this module is
stdlib-only and dependency-free. It provides:

  * :func:`read_event` — parse the hook event JSON from stdin;
  * :func:`log_event` — append a JSONL record when ``CLAUDE_FOUNDATION_LOG_DIR``
    is set (silently a no-op otherwise: logging must never break a hook);
  * :func:`deny` / :func:`allow_with_context` — the documented hook output
    mechanics (``hookSpecificOutput`` JSON on stdout).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

LOG_DIR_ENV = "CLAUDE_FOUNDATION_LOG_DIR"


def read_event(stream: IO[str] | None = None) -> dict[str, Any]:
    """Parse the hook event JSON from ``stream`` (default stdin).

    Raises ``ValueError`` on malformed input — each hook decides its own
    fail-open/fail-closed response (ADR 0002).
    """
    raw = (stream or sys.stdin).read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("hook event must be a JSON object")
    return data


def log_event(hook: str, event: str, **fields: Any) -> None:
    """Append one JSONL record to ``$CLAUDE_FOUNDATION_LOG_DIR/<hook>.jsonl``.

    A no-op when the env var is unset; swallows filesystem errors — audit
    logging must never change hook behavior.
    """
    log_dir = os.environ.get(LOG_DIR_ENV)
    if not log_dir:
        return
    record = {
        "ts": datetime.now(UTC).isoformat(),
        "hook": hook,
        "event": event,
        **fields,
    }
    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"{hook}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def deny(event_name: str, reason: str, *, stream: IO[str] | None = None) -> None:
    """Emit a PreToolUse permission denial on stdout (exit 0 + JSON contract)."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(payload), file=stream or sys.stdout)


def allow_with_context(event_name: str, context: str, *, stream: IO[str] | None = None) -> None:
    """Emit non-blocking additional context for the model on stdout."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }
    print(json.dumps(payload), file=stream or sys.stdout)

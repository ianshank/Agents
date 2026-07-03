#!/usr/bin/env python3
"""PostToolUse audit logger — structured JSONL record per tool call.

Fail-OPEN (ADR 0002) and privacy-conscious: records tool name, session id, and
the *shape* of the input (key names and value sizes) — never raw values, which
could contain secrets. A no-op unless ``CLAUDE_FOUNDATION_LOG_DIR`` is set.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from _lib import LOG_DIR_ENV, log_event, read_event

HOOK = "session-logger"


def input_shape(tool_input: dict[str, Any]) -> dict[str, int]:
    """Map each input key to the length of its serialized value (no raw values)."""
    return {key: len(str(value)) for key, value in tool_input.items()}


def main() -> int:
    if not os.environ.get(LOG_DIR_ENV):
        return 0
    try:
        event = read_event()
        log_event(
            HOOK,
            "tool-call",
            session_id=event.get("session_id"),
            tool=event.get("tool_name"),
            input_shape=input_shape(event.get("tool_input") or {}),
        )
    except Exception as exc:  # fail open: auditing never blocks work
        print(f"{HOOK}: skipped ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

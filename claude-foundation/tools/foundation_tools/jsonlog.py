"""Stdlib JSONL structured logging.

Hooks must run with zero third-party dependencies in arbitrary consumer
environments, so the shared logging convention is stdlib-only (ADR 0003):
one JSON object per line with ``ts``, ``level``, ``logger``, ``event`` and any
extra fields. File output is enabled only when ``CLAUDE_FOUNDATION_LOG_DIR``
is set; stderr always receives the stream so failures surface in transcripts.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_DIR_ENV = "CLAUDE_FOUNDATION_LOG_DIR"
LOG_LEVEL_ENV = "CLAUDE_FOUNDATION_LOG_LEVEL"
_DEFAULT_LEVEL = "INFO"

# Fields supplied by LogRecord itself; anything else on the record is an extra.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
}


class JsonLineFormatter(logging.Formatter):
    """Format each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info and record.exc_info[1] is not None:
            payload["error"] = repr(record.exc_info[1])
        return json.dumps(payload, default=str)


def get_logger(name: str, *, stream: Any = None) -> logging.Logger:
    """Return a configured JSONL logger.

    Emits to ``stream`` (default ``sys.stderr``) always, and additionally to
    ``$CLAUDE_FOUNDATION_LOG_DIR/<name>.jsonl`` when that directory is set.
    Level comes from ``CLAUDE_FOUNDATION_LOG_LEVEL`` (default INFO). Repeat
    calls reuse the already-configured logger.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(os.environ.get(LOG_LEVEL_ENV, _DEFAULT_LEVEL).upper())
    formatter = JsonLineFormatter()

    stream_handler = logging.StreamHandler(stream or sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_dir = os.environ.get(LOG_DIR_ENV)
    if log_dir:
        try:
            directory = Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(directory / f"{name}.jsonl", encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:  # pragma: no cover - depends on host filesystem state
            logger.warning("log dir unusable; falling back to stream only", extra={"dir": log_dir})
    logger.propagate = False
    return logger

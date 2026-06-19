"""Shared time helpers.

Kept tiny and dependency-free so any module (the labeller, the detectors, …)
can parse ISO-8601 timestamps consistently without duplicating the Python <3.11
'Z'-suffix workaround.
"""

from __future__ import annotations

from datetime import datetime, timezone


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into an aware ``datetime``.

    Tolerates a trailing ``Z`` (which ``datetime.fromisoformat`` rejects before
    Python 3.11; agent-core CI runs 3.10) and defaults a naive timestamp to UTC
    so callers always get a comparable, timezone-aware value.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

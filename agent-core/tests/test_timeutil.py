"""Tests for the shared ISO-8601 parser."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_core.timeutil import parse_iso8601

UTC_MIDNIGHT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_parses_z_suffix():
    # 'Z' is rejected by datetime.fromisoformat before Python 3.11.
    assert parse_iso8601("2026-01-01T00:00:00Z") == UTC_MIDNIGHT


def test_parses_explicit_utc_offset():
    assert parse_iso8601("2026-01-01T00:00:00+00:00") == UTC_MIDNIGHT


def test_naive_timestamp_defaults_to_utc():
    assert parse_iso8601("2026-01-01T00:00:00") == UTC_MIDNIGHT


def test_nonzero_offset_normalises_to_utc():
    # 02:00+02:00 is the same instant as 00:00Z.
    assert parse_iso8601("2026-01-01T02:00:00+02:00") == UTC_MIDNIGHT

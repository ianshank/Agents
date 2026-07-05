"""Protocol-version migration tests."""

from __future__ import annotations

import pytest

from flow_protocol.version import (  # type: ignore[import-not-found]
    MIGRATIONS,
    PROTOCOL_VERSION,
    __version__,
    migrate_protocol,
)


def test_current_payload_is_passthrough() -> None:
    data = {"protocol_version": PROTOCOL_VERSION, "instance_id": "i1"}
    assert migrate_protocol(data) == data


def test_missing_version_assumed_current() -> None:
    # Absent protocol_version => treated as current, no migration attempted.
    assert migrate_protocol({"instance_id": "i1"}) == {"instance_id": "i1"}


def test_unknown_old_version_raises() -> None:
    with pytest.raises(ValueError, match="no migration path"):
        migrate_protocol({"protocol_version": "0.0.1"})


def test_migration_chain_runs_when_registered() -> None:
    # Simulate a future bump without permanently editing the module constants.
    original = dict(MIGRATIONS)
    try:
        MIGRATIONS["0.9.0"] = lambda d: {**d, "protocol_version": PROTOCOL_VERSION}
        out = migrate_protocol({"protocol_version": "0.9.0", "x": 1})
        assert out["protocol_version"] == PROTOCOL_VERSION
        assert out["x"] == 1
    finally:
        MIGRATIONS.clear()
        MIGRATIONS.update(original)


def test_cycle_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # A migration that never advances the version must be caught, not loop forever.
    monkeypatch.setitem(MIGRATIONS, "0.5.0", lambda d: {**d, "protocol_version": "0.5.0"})
    with pytest.raises(ValueError, match="migration cycle"):
        migrate_protocol({"protocol_version": "0.5.0"})


def test_distribution_and_protocol_versions_are_strings() -> None:
    assert isinstance(__version__, str)
    assert isinstance(PROTOCOL_VERSION, str)

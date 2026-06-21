from __future__ import annotations

import pytest

from behavioral_regression import version as v


def test_migrate_noop_at_current_version():
    data = {"version": v.SCHEMA_VERSION, "n_pairs": 3}
    assert v.migrate_config(data) == data


def test_migrate_unknown_version_raises():
    with pytest.raises(ValueError, match="no migration path"):
        v.migrate_config({"version": "0.0.1"})


def test_migrate_chain_applies(monkeypatch):
    monkeypatch.setattr(v, "SCHEMA_VERSION", "0.2.0")
    monkeypatch.setattr(v, "MIGRATIONS", {"0.1.0": lambda d: {**d, "version": "0.2.0"}})
    assert v.migrate_config({"version": "0.1.0"})["version"] == "0.2.0"


def test_migrate_cycle_guard(monkeypatch):
    # A migration that fails to advance the version trips the cycle guard.
    monkeypatch.setattr(v, "SCHEMA_VERSION", "9.9.9")
    monkeypatch.setattr(v, "MIGRATIONS", {"0.1.0": lambda d: {**d, "version": "0.1.0"}})
    with pytest.raises(ValueError, match="cycle"):
        v.migrate_config({"version": "0.1.0"})

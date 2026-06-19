"""Tests for the manifest migration chain (backward compatibility)."""
from __future__ import annotations

import pytest
from adguard.errors import ManifestError
from adguard.migrations import MIGRATIONS, SCHEMA_VERSION, migrate_to_current, migration


def test_migrate_0_9_renames_modules_to_components():
    raw = {"schema_version": "0.9", "modules": {"api": ["pkg.api"]}}
    out = migrate_to_current(raw)
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["components"] == {"api": ["pkg.api"]}
    assert "modules" not in out


def test_migrate_current_is_noop():
    raw = {"schema_version": SCHEMA_VERSION, "components": {}}
    assert migrate_to_current(raw)["schema_version"] == SCHEMA_VERSION


def test_missing_schema_version_raises():
    with pytest.raises(ManifestError, match="missing required 'schema_version'"):
        migrate_to_current({"components": {}})


@pytest.mark.parametrize("bad", [["1.0.0"], {"v": "1.0.0"}, 1.0])
def test_non_string_schema_version_raises_manifest_error(bad):
    # Unhashable/non-string versions must raise ManifestError, not TypeError.
    with pytest.raises(ManifestError, match="must be a string"):
        migrate_to_current({"schema_version": bad})


def test_no_migration_path_raises():
    with pytest.raises(ManifestError, match="no migration path"):
        migrate_to_current({"schema_version": "0.1"})


def test_migration_cycle_detected():
    # Register a temporary self-referential pair to force a cycle, then clean up.
    sentinel_a, sentinel_b = "9.9-a", "9.9-b"

    @migration(sentinel_a, sentinel_b)
    def _a(raw):
        return raw

    @migration(sentinel_b, sentinel_a)
    def _b(raw):
        return raw

    try:
        with pytest.raises(ManifestError, match="migration cycle"):
            migrate_to_current({"schema_version": sentinel_a})
    finally:
        MIGRATIONS.pop(sentinel_a, None)
        MIGRATIONS.pop(sentinel_b, None)


def test_modules_not_clobbered_when_components_present():
    raw = {"schema_version": "0.9", "modules": {"a": ["x"]}, "components": {"b": ["y"]}}
    out = migrate_to_current(raw)
    assert out["components"] == {"b": ["y"]}

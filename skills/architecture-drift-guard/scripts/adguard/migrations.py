"""Sequential manifest-schema migrations.

Each migration upgrades a raw manifest dict from one ``schema_version`` to the
next; :func:`migrate_to_current` chains them so a manifest authored against any
past schema loads cleanly on current code. This is the backward-compatibility
hook — old ``architecture.yaml`` files keep working across schema bumps.

Mirrors ``eval_harness.config.migrations`` so the idiom is consistent, but is
vendored to keep the skill self-contained.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import ManifestError

# The current manifest schema version. Bump this (and add a migration below)
# whenever the manifest shape changes in a non-backward-compatible way.
SCHEMA_VERSION = "1.0.0"

# from_version -> (to_version, migrate_fn)
MIGRATIONS: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {}


def migration(from_version: str, to_version: str) -> Callable[
    [Callable[[dict[str, Any]], dict[str, Any]]],
    Callable[[dict[str, Any]], dict[str, Any]],
]:
    """Register a migration from ``from_version`` to ``to_version``."""

    def deco(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
        MIGRATIONS[from_version] = (to_version, fn)
        return fn

    return deco


@migration("0.9", "1.0.0")
def _v0_9_to_1_0_0(raw: dict[str, Any]) -> dict[str, Any]:
    """0.9 named the component map ``modules``; 1.0.0 calls it ``components``."""
    if "modules" in raw and "components" not in raw:
        raw["components"] = raw.pop("modules")
    return raw


def migrate_to_current(raw: dict[str, Any]) -> dict[str, Any]:
    """Walk the migration chain until ``raw`` is at :data:`SCHEMA_VERSION`."""
    raw = dict(raw)
    if "schema_version" not in raw:
        raise ManifestError("manifest is missing required 'schema_version'")
    if not isinstance(raw["schema_version"], str):
        # A non-string (e.g. YAML list/dict) is unhashable and unmappable; reject
        # it as a ManifestError rather than letting it raise a bare TypeError.
        raise ManifestError("'schema_version' must be a string")

    seen: set[str] = set()
    while raw.get("schema_version") != SCHEMA_VERSION:
        current = raw.get("schema_version")
        if current in seen:
            raise ManifestError(f"migration cycle detected at version {current!r}")
        seen.add(current)  # type: ignore[arg-type]
        if current not in MIGRATIONS:
            raise ManifestError(
                f"no migration path from schema_version {current!r} to {SCHEMA_VERSION!r}"
            )
        to_version, fn = MIGRATIONS[current]
        raw = fn(raw)
        raw["schema_version"] = to_version
    return raw

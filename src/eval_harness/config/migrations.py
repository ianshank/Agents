"""Sequential config-schema migrations.

Each migration upgrades a raw config dict from one schema version to the next.
``migrate_to_current`` chains them so a config authored against any past schema
loads cleanly on the current code.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..version import SCHEMA_VERSION


class ConfigError(ValueError):
    pass


# from_version -> (to_version, migrate_fn)
MIGRATIONS: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {}


def migration(from_version: str, to_version: str):
    def deco(fn: Callable[[dict[str, Any]], dict[str, Any]]):
        MIGRATIONS[from_version] = (to_version, fn)
        return fn

    return deco


@migration("0.9", "1.0")
def _v0_9_to_1_0(raw: dict[str, Any]) -> dict[str, Any]:
    """0.9 used singular ``evaluators``/``sink``; 1.0 uses ``scorers``/``sinks``."""
    if "evaluators" in raw:
        raw["scorers"] = raw.pop("evaluators")
    if "sink" in raw and "sinks" not in raw:
        sink = raw.pop("sink")
        raw["sinks"] = [sink] if sink is not None else []
    return raw


def migrate_to_current(raw: dict) -> dict:
    raw = dict(raw)
    if "schema_version" not in raw:
        raise ConfigError("config is missing required 'schema_version'")

    seen: set[str] = set()
    while raw.get("schema_version") != SCHEMA_VERSION:
        current = raw.get("schema_version")
        if current in seen:
            raise ConfigError(f"migration cycle detected at version {current!r}")
        seen.add(current)  # type: ignore[arg-type]
        if current not in MIGRATIONS:
            raise ConfigError(
                f"no migration path from schema_version {current!r} "
                f"to {SCHEMA_VERSION!r}"
            )
        to_version, fn = MIGRATIONS[current]
        raw = fn(raw)
        raw["schema_version"] = to_version
    return raw

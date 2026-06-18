"""Versioning and backwards-compatibility helpers.

Centralises the schema version, the config-migration registry, and a
``deprecated_alias`` decorator so renamed public symbols keep working for a
deprecation window. Keeping all compat logic here (rather than scattered through
modules) means there is exactly one place to audit when bumping versions.
"""
from __future__ import annotations

import functools
import warnings
from typing import Any, Callable, Dict

__version__ = "1.1.0"      # package (distribution) version — single source of truth
SCHEMA_VERSION = "1.1.0"   # config-schema version; may diverge from __version__ later

# --- config migrations -------------------------------------------------------
# Each migration maps an *input* version to a callable that returns a dict at
# the next version. ``migrate_config`` chains them until SCHEMA_VERSION is
# reached, so old persisted configs keep loading without edits at call sites.
ConfigDict = Dict[str, Any]
Migration = Callable[[ConfigDict], ConfigDict]


def _migrate_1_0_0_to_1_1_0(data: ConfigDict) -> ConfigDict:
    """v1.0.0 used ``budget_cap``/``reserve``; v1.1.0 renamed them."""
    data = dict(data)
    budget = dict(data.get("budget", {}))
    if "budget_cap" in budget:
        budget["cap_units"] = budget.pop("budget_cap")
    if "reserve" in budget:
        budget["reserve_fraction"] = budget.pop("reserve")
    data["budget"] = budget
    data["version"] = "1.1.0"
    return data


MIGRATIONS: Dict[str, Migration] = {
    "1.0.0": _migrate_1_0_0_to_1_1_0,
}


def migrate_config(data: ConfigDict) -> ConfigDict:
    """Bring a (possibly old) config dict up to the current schema version."""
    data = dict(data)
    version = data.get("version", SCHEMA_VERSION)
    seen = set()
    while version != SCHEMA_VERSION:
        if version in seen:  # cycle guard – defensive, should never trigger
            raise ValueError(f"migration cycle detected at version {version}")
        seen.add(version)
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"no migration path from config version {version!r} "
                f"to {SCHEMA_VERSION!r}"
            )
        data = migration(data)
        version = data.get("version", SCHEMA_VERSION)
    return data


def deprecated_alias(new_name: str) -> Callable[[Callable], Callable]:
    """Wrap a callable so calling it emits a DeprecationWarning but still works."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                f"{func.__name__!r} is deprecated; use {new_name!r} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator

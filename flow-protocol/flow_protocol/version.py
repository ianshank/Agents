"""Protocol versioning and backwards-compatibility helpers.

This is the *only* shared surface between the flow-calibration corpus and the
validation harness, so its version is the airgap's contract. ``PROTOCOL_VERSION``
is the wire-contract semver; ``__version__`` is the distribution version. They are
kept separate so a packaging release need not imply a contract change.

Mirrors :mod:`agent_core.version`: a single migration registry chains old payloads
up to the current version, additive/backwards-compatible only (semver minor bumps
add optional fields; old payloads keep validating via field defaults).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__version__ = "1.0.0"  # distribution version — single source of truth
PROTOCOL_VERSION = "1.0.0"  # wire-contract semver; may diverge from __version__ later

PayloadDict = dict[str, Any]
Migration = Callable[[PayloadDict], PayloadDict]

# Each migration maps an *input* protocol version to a callable returning a dict at
# the next version. ``migrate_protocol`` chains them until PROTOCOL_VERSION is reached.
# Empty until the first contract bump; additive minor bumps usually need no migration
# (absent optional fields default cleanly in the Pydantic models).
MIGRATIONS: dict[str, Migration] = {}


def migrate_protocol(data: PayloadDict) -> PayloadDict:
    """Bring a (possibly old) serialized payload up to the current PROTOCOL_VERSION."""
    data = dict(data)
    version = data.get("protocol_version", PROTOCOL_VERSION)
    seen: set[str] = set()
    while version != PROTOCOL_VERSION:
        if version in seen:  # cycle guard — defensive, should never trigger
            raise ValueError(f"migration cycle detected at protocol version {version}")
        seen.add(version)
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"no migration path from protocol version {version!r} to {PROTOCOL_VERSION!r}"
            )
        data = migration(data)
        version = data.get("protocol_version", PROTOCOL_VERSION)
    return data

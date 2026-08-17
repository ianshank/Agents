"""Package version, config-schema version, and the backwards-compatible migration chain.

Centralises all version/compat logic (mirrors ``agent_core.version`` and
``flow_corpus.version``). ``migrate_config`` upgrades an older persisted ``BRConfig``
payload to the current schema so configs keep loading across releases.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__version__ = "0.1.0"  # package (distribution) version — single source of truth
SCHEMA_VERSION = "0.1.0"  # config-schema version; may diverge from __version__ later

ConfigDict = dict[str, Any]
Migration = Callable[[ConfigDict], ConfigDict]

# Each migration maps an *input* version to a callable returning a dict at the next
# version. ``migrate_config`` chains them until SCHEMA_VERSION is reached. The chain
# is empty at 0.1.0 (initial schema); new entries are appended on each schema bump.
MIGRATIONS: dict[str, Migration] = {}


def migrate_config(data: ConfigDict) -> ConfigDict:
    """Bring a (possibly older) config dict up to the current schema version.

    This migration-chain-walker pattern is intentionally duplicated across:
    - agent-core/agent_core/version.py
    - behavioral-regression/behavioral_regression/version.py (this file)
    - flow-protocol/flow_protocol/version.py
    - src/eval_harness/config/migrations.py
    See ADR 0034 for rationale: agent-core cannot import from elsewhere, and
    eval_harness uses an incompatible (to_version, fn) tuple shape.
    """
    data = dict(data)
    version = str(data.get("version", SCHEMA_VERSION))
    seen: set[str] = set()
    while version != SCHEMA_VERSION:
        if version in seen:  # cycle guard — defensive, should never trigger
            raise ValueError(f"migration cycle detected at version {version}")
        seen.add(version)
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ValueError(
                f"no migration path from config version {version!r} to {SCHEMA_VERSION!r}"
            )
        data = migration(data)
        version = str(data.get("version", SCHEMA_VERSION))
    return data

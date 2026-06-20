"""Compute the calibration unit key: ``hash(impl + agent_config)``.

The key deliberately **excludes the task instance** — task variation is the
population over which a single ``(agent_version, domain)`` is measured, not part of
its identity. It also excludes any stochastic seed (recorded on the FlowResult, not
the key). Mutating a specimen's implementation or its config re-keys it (and so
triggers trust decay downstream); perturbing the task does not.

Determinism: keys are a SHA-256 over canonical JSON (sorted keys), so they are
stable across runs and independent of dict insertion order — matching the hashing
discipline in ``agent_core.golden._bucket`` / ``outcome_store._fold``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_KEY_LEN = 16  # hex chars retained; 64 bits is ample to avoid collisions across a corpus


def version_key(impl: str, agent_config: Mapping[str, Any]) -> str:
    """Return a stable key for one calibration unit.

    Args:
        impl: implementation identity (e.g. ``"mcts@1"``). Changing the flow code
            should change this string so the unit re-keys.
        agent_config: the agent's configuration knobs (skill, rollout count, ...).
            Must be JSON-serialisable. The task instance must NOT appear here.
    """
    payload = {"impl": impl, "agent_config": _canonical(agent_config)}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:_KEY_LEN]


def _canonical(value: Any) -> Any:
    """Recursively sort mappings so logically-equal configs hash identically."""
    if isinstance(value, Mapping):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value

"""Deterministic hash-bucketing for holdout/cross-check partitioning.

A public, corpus-owned bucketer so the corpus never reaches into a harness
internal (previously ``agent_core.golden._bucket``). The formula is intentionally
identical to that private helper — ``sha256("{seed}:{key}")`` folded into ``[0, 1)``
— so partitions (and therefore every holdout/rotation/cross-check result) are
unchanged by the move. It shares the SHA-256 discipline used by
:mod:`flow_corpus.keying.version_key`.

Order-independent and stable across runs: the bucket depends only on the seed and
the key string, never on insertion order or process state.
"""

from __future__ import annotations

import hashlib

_SCALE = float(1 << 64)
_HEX = 16  # first 16 hex chars == 64 bits of the digest


def bucket(seed: int, key: str) -> float:
    """Map ``(seed, key)`` deterministically into ``[0, 1)``."""
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:_HEX], 16) / _SCALE

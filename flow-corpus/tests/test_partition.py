"""Deterministic bucketer tests, incl. golden values guarding formula identity.

The golden values pin ``bucket`` to the exact sha256 [0,1) formula it shares with
the (private) ``agent_core.golden._bucket`` it replaced — without importing that
private symbol. If the formula ever drifts, every holdout/cross-check partition
would silently move; these literals catch that.
"""

from __future__ import annotations

import hashlib

import pytest

from flow_corpus.partition import bucket


def _reference(seed: int, key: str) -> float:
    # Independent re-derivation of the documented formula (not an import of _bucket).
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:16], 16) / float(1 << 64)


@pytest.mark.parametrize(
    "seed,key",
    [(0, "sdlc-0001"), (7, "react:i42"), (1729, "baseline:x"), (3, "")],
)
def test_bucket_matches_reference_formula(seed: int, key: str) -> None:
    assert bucket(seed, key) == _reference(seed, key)


def test_bucket_is_in_unit_interval() -> None:
    for i in range(100):
        b = bucket(0, f"k{i}")
        assert 0.0 <= b < 1.0


def test_bucket_is_deterministic_and_seed_sensitive() -> None:
    assert bucket(1, "k") == bucket(1, "k")
    assert bucket(1, "k") != bucket(2, "k")

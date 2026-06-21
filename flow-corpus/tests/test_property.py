"""Hypothesis property tests for the pure functions (no metric drift, bounded outputs)."""

from __future__ import annotations

import pytest
from agent_core.calibration import brier_decomposition, selective_risk_coverage
from hypothesis import given
from hypothesis import strategies as st

from flow_corpus.config import CorpusConfig
from flow_corpus.keying import version_key
from flow_corpus.partition import bucket
from flow_corpus.validation import aurc, brier_reliability

pytestmark = pytest.mark.property

CFG = CorpusConfig(power_min_sample=1, n_bins=10)

_probs = st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=200)


@given(seed=st.integers(min_value=-(10**9), max_value=10**9), key=st.text(max_size=40))
def test_bucket_always_in_unit_interval(seed: int, key: str) -> None:
    b = bucket(seed, key)
    assert 0.0 <= b < 1.0
    assert b == bucket(seed, key)  # deterministic


@given(
    keys=st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=6, unique=True),
    vals=st.lists(st.integers(), min_size=1, max_size=6),
)
def test_version_key_is_order_independent(keys: list[str], vals: list[int]) -> None:
    n = min(len(keys), len(vals))
    keys, vals = keys[:n], vals[:n]
    forward = dict(zip(keys, vals, strict=True))
    reversed_ = dict(zip(reversed(keys), reversed(vals), strict=True))
    # Same logical mapping, different insertion order -> identical key.
    if forward == reversed_:
        assert version_key("impl@1", forward) == version_key("impl@1", reversed_)


@given(data=st.data())
def test_brier_reliability_matches_agent_core(data: st.DataObject) -> None:
    probs = data.draw(_probs)
    outcomes = data.draw(
        st.lists(st.integers(min_value=0, max_value=1), min_size=len(probs), max_size=len(probs))
    )
    report = brier_reliability(probs, outcomes, CFG)
    expected = brier_decomposition(probs, outcomes, CFG.n_bins).reliability
    assert report.reliability == pytest.approx(expected)


@given(data=st.data())
def test_aurc_is_bounded(data: st.DataObject) -> None:
    probs = data.draw(_probs)
    outcomes = data.draw(
        st.lists(st.integers(min_value=0, max_value=1), min_size=len(probs), max_size=len(probs))
    )
    value = aurc(selective_risk_coverage(probs, outcomes))
    assert 0.0 <= value <= 1.0  # risk is a rate in [0,1]; AURC integrates over coverage in [0,1]

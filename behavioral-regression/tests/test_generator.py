from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from behavioral_regression.config import BRConfig  # type: ignore[import-not-found]
from behavioral_regression.generator import (  # type: ignore[import-not-found]
    PairedResponseGenerator,
    ground_truth_regressions,
    sycophancy_indicators,
)


def _gen(cfg, seed, **kw):
    return PairedResponseGenerator(cfg).generate(random.Random(seed), **kw)


def test_same_seed_identical_different_seed_differs():
    cfg = BRConfig(n_pairs=50)
    assert _gen(cfg, 1) == _gen(cfg, 1)
    assert _gen(cfg, 1) != _gen(cfg, 2)


def test_n_override_and_invalid():
    cfg = BRConfig(n_pairs=10)
    assert len(_gen(cfg, 1, n=5)) == 5
    with pytest.raises(ValueError, match="must be > 0"):
        _gen(cfg, 1, n=0)


def test_v2_shift_raises_sycophancy_rate():
    cfg = BRConfig(n_pairs=500, v1_sycophancy_mean=0.3, v2_sycophancy_mean=0.3)
    pairs = _gen(cfg, 3, v2_shift=0.4)
    v1, v2 = sycophancy_indicators(pairs)
    assert sum(v2) > sum(v1)


def test_clamp_to_unit_interval_extremes():
    # Means at the edges + a large shift exercise both clamps in _clamped_draw and v2_mean.
    cfg = BRConfig(n_pairs=80, v1_sycophancy_mean=1.0, v2_sycophancy_mean=0.0, dist_sigma=0.5)
    pairs = _gen(cfg, 5, v2_shift=2.0)
    for p in pairs:
        assert 0.0 <= p.v1_sycophancy <= 1.0
        assert 0.0 <= p.v2_sycophancy <= 1.0


def test_text_labels_both_branches():
    cfg = BRConfig(n_pairs=200, v1_sycophancy_mean=0.5, v2_sycophancy_mean=0.5, dist_sigma=0.4)
    pairs = _gen(cfg, 9)
    texts = {p.v1_text for p in pairs} | {p.v2_text for p in pairs}
    assert "v1:sycophantic" in texts or "v2:sycophantic" in texts
    assert "v1:candid" in texts or "v2:candid" in texts


def test_ground_truth_matches_scores():
    cfg = BRConfig(n_pairs=20)
    pairs = _gen(cfg, 7)
    gt = ground_truth_regressions(pairs)
    assert gt == [p.v2_sycophancy > p.v1_sycophancy for p in pairs]


@given(seed=st.integers(min_value=0, max_value=10_000))
def test_indicator_lengths_match(seed):
    cfg = BRConfig(n_pairs=30)
    pairs = _gen(cfg, seed)
    v1, v2 = sycophancy_indicators(pairs)
    assert len(v1) == len(v2) == 30

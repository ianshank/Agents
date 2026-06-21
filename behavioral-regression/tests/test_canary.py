from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from behavioral_regression.canary import CanaryReport, run_canary
from behavioral_regression.config import BRConfig


def test_canary_separates_known_regression_from_null():
    cfg = BRConfig(n_pairs=400)
    rep = run_canary(cfg, seed=7)
    assert rep.regressed_p > rep.null_p
    assert rep.margin >= cfg.min_canary_margin
    assert rep.separated is True
    assert rep.passes is True


def test_canary_deterministic():
    cfg = BRConfig(n_pairs=200)
    assert run_canary(cfg, 1) == run_canary(cfg, 1)


def test_report_not_separated_when_margin_below_threshold():
    rep = CanaryReport(regressed_p=0.5, null_p=0.45, margin=0.05, separated=False)
    assert rep.passes is False


@pytest.mark.property
@settings(deadline=None, max_examples=40)
@given(seed=st.integers(min_value=0, max_value=300))
def test_detector_orders_regression_above_null(seed):
    # The discrimination property: the known-regression arm always reads higher than
    # the known-null arm. (The strict ``separated`` margin is config-tunable and checked
    # at a fixed seed above; ordering is the invariant.) A lighter bootstrap keeps the
    # property test fast without changing the ordering it asserts.
    cfg = BRConfig(n_pairs=300, bootstrap_resamples=200)
    rep = run_canary(cfg, seed)
    assert rep.regressed_p > rep.null_p

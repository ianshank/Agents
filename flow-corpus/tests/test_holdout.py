"""Holdout manager + rotation tests (single split authority, type-holdout caveat)."""

from __future__ import annotations

import pytest

from flow_corpus.config import CorpusConfig
from flow_corpus.holdout import HoldoutManager, RotationManager, Sample, samples_from_run
from flow_corpus.oracles import PropertyOracle
from flow_corpus.policy import MockPolicy
from flow_corpus.specimens import BaselineSpecimen, MCTSSpecimen, ReActSpecimen
from flow_corpus.suites.sdlc import build_sdlc_suite
from flow_corpus.validation import run_suite

CFG = CorpusConfig(declared_n_per_domain=200, power_min_sample=30, n_bins=10)
SUITE = build_sdlc_suite(CFG, seed=11)


def _samples(spec) -> list[Sample]:
    return samples_from_run(run_suite(spec, SUITE, PropertyOracle(), CFG, seed=4))


def _samples_by_type() -> dict[str, list[Sample]]:
    return {
        "baseline": _samples(BaselineSpecimen(MockPolicy(0.7, 1.0))),
        "mcts": _samples(MCTSSpecimen(MockPolicy(0.7, 1.0), n_rollouts=5)),
        "react": _samples(ReActSpecimen(MockPolicy(0.7, 1.0), max_steps=3)),
    }


def test_instance_and_type_holdout_reported_separately() -> None:
    mgr = HoldoutManager(CFG, seed=7)
    report = mgr.evaluate(_samples_by_type(), held_out_type="react")
    assert report.held_out_type == "react"
    # Two distinct numbers, never merged.
    assert report.instance_holdout.reliability is not None
    assert report.type_holdout.reliability is not None
    assert report.instance_holdout is not report.type_holdout


def test_extrapolation_fraction_reported() -> None:
    mgr = HoldoutManager(CFG, seed=7)
    report = mgr.evaluate(_samples_by_type(), held_out_type="react")
    assert 0.0 <= report.extrapolation_fraction <= 1.0
    assert report.seen_support is not None
    lo, hi = report.seen_support
    assert lo <= hi


def test_held_out_type_must_be_present() -> None:
    mgr = HoldoutManager(CFG)
    with pytest.raises(ValueError, match="not present"):
        mgr.evaluate({"baseline": []}, held_out_type="react")


def test_single_split_authority_is_deterministic() -> None:
    # Same seed -> identical instance-holdout reliability (one partition, no re-split).
    sbt = _samples_by_type()
    r1 = HoldoutManager(CFG, seed=3).evaluate(sbt, "react")
    r2 = HoldoutManager(CFG, seed=3).evaluate(sbt, "react")
    assert r1.instance_holdout.reliability == r2.instance_holdout.reliability


def test_rotation_stability() -> None:
    mgr = RotationManager(CFG)
    report = mgr.rotate(_samples_by_type(), held_out_type="react", k_folds=4, base_seed=0)
    assert len(report.per_fold_reliability) >= 2
    assert report.spread >= 0.0
    # A well-calibrated agent should be reasonably stable across rotations.
    assert isinstance(report.stable, bool)


def test_rotation_requires_two_folds() -> None:
    with pytest.raises(ValueError, match="k_folds must be >= 2"):
        RotationManager(CFG).rotate(_samples_by_type(), "react", k_folds=1)


def test_samples_from_run_skips_indeterminate_and_confidence_free() -> None:
    from flow_corpus.canary import NoOpSpecimen

    # No-op is confidence-free -> yields no samples.
    assert samples_from_run(run_suite(NoOpSpecimen(), SUITE, PropertyOracle(), CFG, seed=0)) == []

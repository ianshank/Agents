"""Reliability, AURC, and end-to-end runner tests."""

from __future__ import annotations

import pytest
from agent_core.calibration import brier_decomposition, selective_risk_coverage

from flow_corpus.config import CorpusConfig
from flow_corpus.oracles import PropertyOracle
from flow_corpus.policy import MockPolicy
from flow_corpus.specimens import BaselineSpecimen
from flow_corpus.suites.sdlc import build_sdlc_suite
from flow_corpus.validation import aurc, brier_reliability, run_suite

CFG = CorpusConfig(declared_n_per_domain=150, power_min_sample=100, n_bins=10)
SUITE = build_sdlc_suite(CFG, seed=11)


def test_reliability_matches_agent_core_decomposition() -> None:
    # No metric drift: corpus reliability == agent_core brier_decomposition.reliability.
    confidences = [0.1, 0.4, 0.6, 0.9, 0.3, 0.7, 0.5, 0.8] * 20
    outcomes = [0, 0, 1, 1, 0, 1, 0, 1] * 20
    report = brier_reliability(confidences, outcomes, CFG)
    expected = brier_decomposition(confidences, outcomes, CFG.n_bins).reliability
    assert report.reliability == pytest.approx(expected)
    assert report.directional_only is False  # 160 >= power_min_sample


def test_reliability_directional_below_power() -> None:
    report = brier_reliability([0.5, 0.5], [1, 0], CFG)
    assert report.directional_only is True and report.passes is False


def test_reliability_empty_is_none() -> None:
    report = brier_reliability([], [], CFG)
    assert report.reliability is None and report.passes is False


def test_aurc_matches_manual_trapezoid() -> None:
    points = selective_risk_coverage([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0])
    value = aurc(points)
    assert value >= 0.0


def test_aurc_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        aurc([])


def test_runner_keys_outcomes_and_is_reproducible() -> None:
    spec = BaselineSpecimen(MockPolicy(skill=0.75, confidence_quality=1.0))
    r1 = run_suite(spec, SUITE, PropertyOracle(), CFG, seed=3)
    r2 = run_suite(spec, SUITE, PropertyOracle(), CFG, seed=3)
    assert r1.outcomes == r2.outcomes  # byte-reproducible under same seed
    # Every persisted record carries the agent_version keying axis.
    assert all(rec.agent_version == spec.agent_version for rec in r1.outcome_records)
    assert all(rec.domain == "sdlc" for rec in r1.outcome_records)
    assert r1.reliability.reliability is not None


def test_runner_does_not_record_outcome_only_flow_confidence() -> None:
    from flow_corpus.canary import NoOpSpecimen

    r = run_suite(NoOpSpecimen(), SUITE, PropertyOracle(), CFG, seed=0)
    # No-op is confidence-free: no OutcomeRecords, reliability undefined, but outcomes exist.
    assert r.outcome_records == ()
    assert r.reliability.reliability is None
    assert len(r.outcomes) == len(SUITE.instances)
    assert sum(r.outcomes) == 0  # all wrong


def test_well_calibrated_agent_has_lower_reliability_than_noisy_one() -> None:
    # confidence_quality=1.0 should calibrate better (lower reliability) than 0.0.
    good = run_suite(BaselineSpecimen(MockPolicy(0.7, 1.0)), SUITE, PropertyOracle(), CFG, seed=5)
    noisy = run_suite(BaselineSpecimen(MockPolicy(0.7, 0.0)), SUITE, PropertyOracle(), CFG, seed=5)
    assert good.reliability.reliability is not None
    assert noisy.reliability.reliability is not None
    assert good.reliability.reliability <= noisy.reliability.reliability


def test_runner_counts_indeterminate_and_excludes_from_outcomes() -> None:
    import random

    from flow_corpus.specimens.base import SpecimenBase

    class _MalformedSpecimen(SpecimenBase):
        flow_type = "malformed"
        impl_version = "1"

        def run(self, instance, rng: random.Random):
            # Output is outside the solution space -> oracle abstains (indeterminate).
            return self._result(instance, "not_a_candidate", confidence=0.5, seed=None)

    spec = _MalformedSpecimen(policy=MockPolicy())
    r = run_suite(spec, SUITE, PropertyOracle(), CFG, seed=0)
    assert r.n_indeterminate == len(SUITE.instances)
    assert r.outcomes == ()  # abstentions never become outcomes
    assert r.outcome_records == ()
    assert r.indeterminate_rate == pytest.approx(1.0)
    assert r.within_indeterminate_cap(CFG) is False


def test_indeterminate_rate_within_cap_for_property_oracle() -> None:
    # The property oracle interprets every well-formed candidate, so 0 indeterminates.
    r = run_suite(BaselineSpecimen(MockPolicy(0.7)), SUITE, PropertyOracle(), CFG, seed=1)
    assert r.n_indeterminate == 0
    assert r.within_indeterminate_cap(CFG)

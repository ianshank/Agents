"""Oracle + κ-gate tests, including the indeterminate-filtering and power corrections."""

from __future__ import annotations

import random

import pytest

from flow_corpus.config import CorpusConfig  # type: ignore[import-not-found]
from flow_corpus.oracles import PropertyOracle, validate_oracle  # type: ignore[import-not-found]
from flow_corpus.policy import MockPolicy  # type: ignore[import-not-found]
from flow_corpus.specimens import BaselineSpecimen  # type: ignore[import-not-found]
from flow_corpus.suites.base import TaskInstance  # type: ignore[import-not-found]

INSTANCE = TaskInstance(
    instance_id="t1",
    domain="sdlc",
    solution_space=("a", "b", "c", "d"),
    correct=("a",),
)


def test_property_oracle_passes_correct_and_fails_wrong() -> None:
    oracle = PropertyOracle()
    spec = BaselineSpecimen(MockPolicy(skill=1.0))  # always correct
    good = spec.run(INSTANCE, random.Random(0))
    assert oracle.judge(INSTANCE, good).verdict is True

    spec_bad = BaselineSpecimen(MockPolicy(skill=0.0))  # always wrong
    bad = spec_bad.run(INSTANCE, random.Random(0))
    assert oracle.judge(INSTANCE, bad).verdict is False


def test_property_oracle_abstains_on_uninterpretable_output() -> None:
    oracle = PropertyOracle()
    fr = BaselineSpecimen(MockPolicy()).run(INSTANCE, random.Random(0))
    malformed = fr.model_copy(update={"output": "not_a_candidate"})
    res = oracle.judge(INSTANCE, malformed)
    assert res.verdict is None and res.is_indeterminate


def test_kappa_gate_blocks_disagreeing_oracle() -> None:
    cfg = CorpusConfig(power_min_sample=10, min_oracle_kappa=0.8)
    # Oracle disagrees with human on most cases -> low kappa -> may not gate.
    oracle_v = [True, False] * 20
    human_v = [False, True] * 20
    report = validate_oracle(oracle_v, human_v, cfg)
    assert report.kappa is not None and report.kappa < 0.8
    assert report.passes is False


def test_kappa_gate_passes_agreeing_oracle() -> None:
    cfg = CorpusConfig(power_min_sample=10, min_oracle_kappa=0.8)
    labels = [True, False, True, True, False] * 8  # 40 pairs, perfect agreement
    report = validate_oracle(labels, list(labels), cfg)
    assert report.kappa == pytest.approx(1.0)
    assert report.passes is True


def test_kappa_gate_excludes_indeterminate_pairs() -> None:
    cfg = CorpusConfig(power_min_sample=3, min_oracle_kappa=0.8)
    # Indeterminates (None) on either side must be dropped, not coerced to a category.
    oracle_v = [True, None, False, True, None]
    human_v = [True, False, False, True, True]
    report = validate_oracle(oracle_v, human_v, cfg)
    assert report.n_codeterminate == 3  # only the 3 both-decided pairs count
    assert report.kappa == pytest.approx(1.0)


def test_kappa_gate_directional_below_power() -> None:
    cfg = CorpusConfig(power_min_sample=100, min_oracle_kappa=0.8)
    report = validate_oracle([True, True], [True, True], cfg)
    assert report.directional_only is True
    assert report.passes is False  # cannot gate below power, even at kappa 1.0


def test_kappa_gate_no_codeterminate_pairs() -> None:
    cfg = CorpusConfig()
    report = validate_oracle([None, None], [True, False], cfg)
    assert report.kappa is None and report.passes is False


def test_kappa_gate_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="aligned"):
        validate_oracle([True], [True, False], CorpusConfig())

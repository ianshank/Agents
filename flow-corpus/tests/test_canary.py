"""Canary tests: gold separates from no-op via Wilson-bounded pass-rate margin."""

from __future__ import annotations

import random

import pytest

from flow_corpus.canary import (
    GoldSpecimen,
    NoOpSpecimen,
    RandomSpecimen,
    canary_separation,
)
from flow_corpus.config import CorpusConfig
from flow_corpus.oracles import PropertyOracle
from flow_corpus.suites.sdlc import build_sdlc_suite

CFG = CorpusConfig(declared_n_per_domain=120, min_canary_margin=0.5)
SUITE = build_sdlc_suite(CFG, seed=7)
ORACLE = PropertyOracle()


def _outcomes(spec) -> list[int]:
    rng = random.Random(0)
    out: list[int] = []
    for inst in SUITE.instances:
        fr = spec.run(inst, rng)
        v = ORACLE.judge(inst, fr).verdict
        out.append(1 if v else 0)
    return out


def test_gold_separates_from_noop() -> None:
    gold = _outcomes(GoldSpecimen())
    noop = _outcomes(NoOpSpecimen())
    report = canary_separation(gold, noop, CFG)
    assert sum(gold) == len(gold)  # gold passes everything
    assert sum(noop) == 0  # no-op passes nothing
    assert report.separated is True
    assert report.margin >= CFG.min_canary_margin


def test_random_is_between_gold_and_noop() -> None:
    rand = _outcomes(RandomSpecimen())
    # ~1/4 correct (1 correct of 4 candidates), so neither separated-high nor zero.
    assert 0 < sum(rand) < len(rand)


def test_noop_is_outcome_only_no_confidence() -> None:
    fr = NoOpSpecimen().run(SUITE.instances[0], random.Random(0))
    assert fr.raw_confidence is None  # single-class + confidence-free -> AUROC undefined


def test_separation_empty_outcomes_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        canary_separation([], [0], CFG)

from __future__ import annotations

import random

from behavioral_regression.config import BRConfig
from behavioral_regression.generator import PairedResponse
from behavioral_regression.judge import JudgeProtocol, SyntheticJudge


def _pair(v1, v2):
    return PairedResponse("p", "a", "b", v1, v2)


def test_indeterminate_band_abstains():
    cfg = BRConfig(judge_indeterminate_band=0.10)
    j = SyntheticJudge(cfg, random.Random(0))
    v = j.judge(_pair(0.50, 0.52))  # |delta| = 0.02 < band
    assert v.label is None and v.confidence == 0.0


def test_determinate_verdict_no_noise():
    cfg = BRConfig(judge_noise=0.0, judge_indeterminate_band=0.01)
    j = SyntheticJudge(cfg, random.Random(0))
    assert j.judge(_pair(0.2, 0.8)).label is True
    assert j.judge(_pair(0.8, 0.2)).label is False


def test_noise_flips_verdict():
    cfg = BRConfig(judge_noise=0.999, judge_indeterminate_band=0.01)
    j = SyntheticJudge(cfg, random.Random(0))
    # delta > 0 ⇒ true verdict True, but near-certain noise flips it to False.
    assert j.judge(_pair(0.2, 0.8)).label is False


def test_bias_clamps_confidence():
    hi = SyntheticJudge(BRConfig(judge_bias=1.0, judge_noise=0.0), random.Random(0))
    assert hi.judge(_pair(0.2, 0.8)).confidence == 1.0
    lo = SyntheticJudge(BRConfig(judge_bias=-1.0, judge_noise=0.0), random.Random(0))
    assert lo.judge(_pair(0.45, 0.55)).confidence == 0.0


def test_satisfies_protocol():
    j = SyntheticJudge(BRConfig(), random.Random(0))
    assert isinstance(j, JudgeProtocol)


def test_deterministic_given_rng():
    cfg = BRConfig()
    pair = _pair(0.3, 0.6)
    a = SyntheticJudge(cfg, random.Random(11)).judge(pair)
    b = SyntheticJudge(cfg, random.Random(11)).judge(pair)
    assert a == b

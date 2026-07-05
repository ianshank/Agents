from __future__ import annotations

import pytest

from behavioral_regression.config import BRConfig  # type: ignore[import-not-found]
from behavioral_regression.judge import JVerdict  # type: ignore[import-not-found]
from behavioral_regression.oracle import validate_judge  # type: ignore[import-not-found]


def _verdicts(labels):
    return [JVerdict(label=lbl, confidence=0.9) for lbl in labels]


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="aligned"):
        validate_judge(_verdicts([True]), [True, False], BRConfig())


def test_perfect_agreement_gates():
    cfg = BRConfig(power_min_sample=5, min_judge_kappa=0.6)
    labels = [True, False] * 20
    rep = validate_judge(_verdicts(labels), labels, cfg)
    assert rep.kappa == 1.0
    assert rep.may_gate is True


def test_disagreement_does_not_gate():
    cfg = BRConfig(power_min_sample=5, min_judge_kappa=0.9)
    judge = [True, False] * 20
    human = [False, True] * 20  # systematic disagreement
    rep = validate_judge(_verdicts(judge), human, cfg)
    assert rep.may_gate is False


def test_below_power_is_directional_only():
    cfg = BRConfig(power_min_sample=100, min_judge_kappa=0.1)
    labels = [True, False, True, False]
    rep = validate_judge(_verdicts(labels), labels, cfg)
    assert rep.directional_only is True
    assert rep.may_gate is False


def test_indeterminates_excluded():
    cfg = BRConfig(power_min_sample=2, min_judge_kappa=0.5)
    judge = [None, True, False, None]
    human = [True, True, False, False]
    rep = validate_judge(_verdicts(judge), human, cfg)
    assert rep.n_codeterminate == 2  # only the two co-determinate pairs count

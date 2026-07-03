from __future__ import annotations

import logging

import pytest

from behavioral_regression.config import BRConfig
from behavioral_regression.detector import RegressionDetector, labelled_correctness
from behavioral_regression.judge import JVerdict


def _verdicts(labels, conf=0.8):
    return [JVerdict(label=lbl, confidence=conf) for lbl in labels]


def test_alignment_and_empty_errors():
    det = RegressionDetector(BRConfig())
    with pytest.raises(ValueError, match="aligned"):
        det.detect([1, 0], [1], _verdicts([True, False]), None, seed=0)
    with pytest.raises(ValueError, match="empty"):
        det.detect([], [], [], None, seed=0)


def test_human_labels_length_mismatch_raises():
    det = RegressionDetector(BRConfig())
    with pytest.raises(ValueError, match="aligned"):
        det.detect([1, 0], [1, 0], _verdicts([True, False]), [True], seed=0)


def test_labelled_correctness_mismatch_raises():
    with pytest.raises(ValueError, match="aligned"):
        labelled_correctness(_verdicts([True]), [True, False])


def test_no_human_labels_leaves_brier_none():
    det = RegressionDetector(BRConfig(power_min_sample=2))
    est = det.detect([0, 0, 1], [0, 1, 1], _verdicts([True, None, False]), None, seed=1)
    assert est.brier is None and est.reliability is None
    assert est.n_determinate == 2


def test_brier_computed_with_labels():
    cfg = BRConfig(power_min_sample=2, n_bins=4)
    n = 40
    v1 = [0] * n
    v2 = [1] * n
    verdicts = _verdicts([True] * n)
    human = [True] * n  # judge always correct
    est = RegressionDetector(cfg).detect(v1, v2, verdicts, human, seed=2)
    assert est.brier is not None and est.reliability is not None
    assert est.p_regression == 1.0


def test_all_indeterminate_zero_proportion():
    cfg = BRConfig(power_min_sample=2)
    est = RegressionDetector(cfg).detect([0, 1], [1, 0], _verdicts([None, None]), None, seed=3)
    assert est.n_determinate == 0
    assert est.p_regression == 0.0
    assert (est.wilson_low, est.wilson_high) == (0.0, 0.0)
    assert est.cant_tell is True  # directional + CI includes zero


def test_all_indeterminate_logs_degrade_warning(caplog):
    cfg = BRConfig(power_min_sample=2)
    with caplog.at_level(logging.WARNING, logger="behavioral_regression.detector"):
        RegressionDetector(cfg).detect([0, 1], [1, 0], _verdicts([None, None]), None, seed=3)
    assert "no determinate verdicts out of 2 pairs" in caplog.text


def test_detect_outcome_is_logged(caplog):
    cfg = BRConfig(power_min_sample=2)
    with caplog.at_level(logging.INFO, logger="behavioral_regression.detector"):
        est = RegressionDetector(cfg).detect(
            [0, 0, 1], [0, 1, 1], _verdicts([True, None, False]), None, seed=1
        )
    assert "detect: p_regression=" in caplog.text
    assert "n_determinate=2/3" in caplog.text
    assert f"cant_tell={est.cant_tell}" in caplog.text
    # no degrade warning on a determinate sample
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_cant_tell_false_on_clear_regression():
    cfg = BRConfig(power_min_sample=5)
    n = 60
    est = RegressionDetector(cfg).detect(
        [0] * n, [1] * n, _verdicts([True] * n), [True] * n, seed=4
    )
    assert est.excludes_zero is True
    assert est.cant_tell is False

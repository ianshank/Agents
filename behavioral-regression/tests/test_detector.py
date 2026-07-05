from __future__ import annotations

import pytest

from behavioral_regression.config import BRConfig  # type: ignore[import-not-found]
from behavioral_regression.detector import RegressionDetector, labelled_correctness  # type: ignore[import-not-found]
from behavioral_regression.judge import JVerdict  # type: ignore[import-not-found]


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


def test_cant_tell_false_on_clear_regression():
    cfg = BRConfig(power_min_sample=5)
    n = 60
    est = RegressionDetector(cfg).detect(
        [0] * n, [1] * n, _verdicts([True] * n), [True] * n, seed=4
    )
    assert est.excludes_zero is True
    assert est.cant_tell is False

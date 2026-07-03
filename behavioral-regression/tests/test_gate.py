from __future__ import annotations

import logging

from flow_corpus.oracles.kappa_gate import KappaReport
from flow_corpus.validation.resampling import BootstrapCI

from behavioral_regression.canary import CanaryReport
from behavioral_regression.config import BRConfig
from behavioral_regression.detector import RegressionEstimate
from behavioral_regression.gate import ShipDecision, decide_ship


def _estimate(*, point, low, high, p_regression, cant_tell):
    ci = BootstrapCI(point=point, low=low, high=high, n_resamples=100)
    return RegressionEstimate(
        p_regression=p_regression,
        wilson_low=0.0,
        wilson_high=1.0,
        delta_ci=ci,
        brier=0.1,
        reliability=0.05,
        n_determinate=200,
        cant_tell=cant_tell,
    )


def _kappa(may_gate):
    return KappaReport(
        kappa=0.9 if may_gate else 0.1,
        n_codeterminate=200,
        n_total=200,
        directional_only=False,
        may_gate=may_gate,
    )


def _canary(separated):
    return CanaryReport(regressed_p=0.8, null_p=0.4, margin=0.4, separated=separated)


CFG = BRConfig(ship_risk_target=0.5)
OK_EST = _estimate(point=0.3, low=0.1, high=0.5, p_regression=0.8, cant_tell=False)


def test_escalate_when_canary_not_separated():
    d = decide_ship(OK_EST, _kappa(True), _canary(False), CFG)
    assert d is ShipDecision.ESCALATE


def test_escalate_when_judge_not_validated():
    d = decide_ship(OK_EST, _kappa(False), _canary(True), CFG)
    assert d is ShipDecision.ESCALATE


def test_escalate_when_cant_tell():
    est = _estimate(point=0.3, low=0.1, high=0.5, p_regression=0.8, cant_tell=True)
    d = decide_ship(est, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.ESCALATE


def test_hold_on_real_regression_above_target():
    d = decide_ship(OK_EST, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.HOLD


def test_ship_when_drift_negative():
    est = _estimate(point=-0.2, low=-0.4, high=-0.05, p_regression=0.2, cant_tell=False)
    d = decide_ship(est, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.SHIP


def test_ship_when_positive_but_below_risk_target():
    # CI excludes zero positive, but p_regression under the risk target ⇒ ship.
    est = _estimate(point=0.3, low=0.1, high=0.5, p_regression=0.3, cant_tell=False)
    d = decide_ship(est, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.SHIP


def test_ship_when_positive_point_but_ci_includes_zero_is_not_real():
    # point > 0 but CI spans zero ⇒ not a "real" regression; cant_tell False here so ships.
    est = _estimate(point=0.1, low=-0.05, high=0.25, p_regression=0.9, cant_tell=False)
    d = decide_ship(est, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.SHIP


def test_ship_verdict_is_logged_with_deciding_numbers(caplog):
    est = _estimate(point=-0.2, low=-0.4, high=-0.05, p_regression=0.2, cant_tell=False)
    with caplog.at_level(logging.INFO, logger="behavioral_regression.gate"):
        d = decide_ship(est, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.SHIP
    assert "verdict=SHIP" in caplog.text
    assert "p_regression=0.2000" in caplog.text
    assert f"ship_risk_target={CFG.ship_risk_target:.4f}" in caplog.text


def test_hold_verdict_is_logged_with_deciding_numbers(caplog):
    with caplog.at_level(logging.INFO, logger="behavioral_regression.gate"):
        d = decide_ship(OK_EST, _kappa(True), _canary(True), CFG)
    assert d is ShipDecision.HOLD
    assert "verdict=HOLD" in caplog.text
    assert "p_regression=0.8000" in caplog.text
    assert f"ship_risk_target={CFG.ship_risk_target:.4f}" in caplog.text
    assert "delta_point=0.3000" in caplog.text


def test_escalate_verdicts_are_logged_with_reasons(caplog):
    cant_tell_est = _estimate(point=0.3, low=0.1, high=0.5, p_regression=0.8, cant_tell=True)
    with caplog.at_level(logging.INFO, logger="behavioral_regression.gate"):
        assert decide_ship(OK_EST, _kappa(True), _canary(False), CFG) is ShipDecision.ESCALATE
        assert decide_ship(OK_EST, _kappa(False), _canary(True), CFG) is ShipDecision.ESCALATE
        assert decide_ship(cant_tell_est, _kappa(True), _canary(True), CFG) is ShipDecision.ESCALATE
    assert "verdict=ESCALATE reason=canary_not_separated" in caplog.text
    assert "verdict=ESCALATE reason=judge_not_validated" in caplog.text
    assert "verdict=ESCALATE reason=cant_tell" in caplog.text

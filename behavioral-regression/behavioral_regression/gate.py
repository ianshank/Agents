"""Ship / hold / escalate gate — fail-safe-to-escalate.

Mirrors the layered, conservative shape of ``agent_core.merge_gate.decide``: the gate
ESCALATEs (routes to a human) whenever the apparatus can't be trusted or the measurement
can't tell, HOLDs a real regression, and only SHIPs a change that is validated, separable,
and below the configured risk target. Every threshold comes from ``BRConfig`` — no literal
appears in the decision logic.
"""

from __future__ import annotations

from enum import Enum

from agent_core.logging_util import get_logger
from flow_corpus.oracles.kappa_gate import KappaReport

from .canary import CanaryReport
from .config import BRConfig
from .detector import RegressionEstimate

_log = get_logger("behavioral_regression.gate")


class ShipDecision(str, Enum):
    SHIP = "ship"
    HOLD = "hold"  # a real regression — do not ship v2
    ESCALATE = "escalate"  # route to a human; fail-safe default


def decide_ship(
    estimate: RegressionEstimate,
    kappa: KappaReport,
    canary: CanaryReport,
    cfg: BRConfig,
) -> ShipDecision:
    """Decide SHIP / HOLD / ESCALATE for a v1→v2 behavioural change.

    Layering (each falls safe to ESCALATE):
      1. canary not separated  → ESCALATE  (the detector can't tell good from bad)
      2. judge not κ-validated → ESCALATE  (an unvalidated judge is advisory, not a gate)
      3. estimate.cant_tell    → ESCALATE  (measurement stops working here)
      4. significant positive drift above the risk target → HOLD  (regression is real)
      5. otherwise             → SHIP
    """
    if not canary.separated:
        _log.info(
            "verdict=ESCALATE reason=canary_not_separated margin=%.4f min_canary_margin=%.4f",
            canary.margin,
            cfg.min_canary_margin,
        )
        return ShipDecision.ESCALATE
    if not kappa.may_gate:
        _log.info(
            "verdict=ESCALATE reason=judge_not_validated kappa=%s n_codeterminate=%d",
            kappa.kappa,
            kappa.n_codeterminate,
        )
        return ShipDecision.ESCALATE
    if estimate.cant_tell:
        _log.info(
            "verdict=ESCALATE reason=cant_tell n_determinate=%d excludes_zero=%s",
            estimate.n_determinate,
            estimate.excludes_zero,
        )
        return ShipDecision.ESCALATE
    regression_real = estimate.delta_ci.point > 0.0 and estimate.excludes_zero
    if regression_real and estimate.p_regression > cfg.ship_risk_target:
        _log.info(
            "verdict=HOLD p_regression=%.4f ship_risk_target=%.4f delta_point=%.4f",
            estimate.p_regression,
            cfg.ship_risk_target,
            estimate.delta_ci.point,
        )
        return ShipDecision.HOLD
    _log.info(
        "verdict=SHIP p_regression=%.4f ship_risk_target=%.4f regression_real=%s",
        estimate.p_regression,
        cfg.ship_risk_target,
        regression_real,
    )
    return ShipDecision.SHIP

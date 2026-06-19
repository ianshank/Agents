"""Calibrated auto-merge gate.

A mechanically-enforced policy that decides MERGE / ESCALATE / REJECT for an
agent-authored change, in place of a blanket human review label. It does NOT
replace mechanical checks or the protected-path human gate.

Design invariants (do not relax without a design review — see ADR 0005):
  * Mechanical checks are ground truth. Calibration buys skipping *human
    review*, never skipping tests. A failed regression gate is an unconditional
    REJECT regardless of agent confidence.
  * Protected (eval-defining) paths NEVER auto-merge. Autonomy applies to
    product code, not to the apparatus that measures it.
  * The merge threshold is *derived from an acceptable-risk target*, never a
    hardcoded probability. ``tau`` is computed from the selective-risk curve.
  * Calibration is only trusted when the calibrator is healthy (enough samples,
    low ECE, AUROC that actually rank-orders correctness, tight CI).

Pure and deterministic: every tunable lives on :class:`GatePolicyConfig`; no
literal appears in decision logic. The Wilson math is reused from
:mod:`agent_core.calibration` rather than re-implemented.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .calibration import wilson_interval


class GateDecision(str, Enum):
    AUTO_MERGE = "auto_merge"
    ESCALATE = "escalate"  # human (or higher-authority agent) review
    REJECT = "reject"  # mechanical ground-truth failure


@dataclass(frozen=True)
class GatePolicyConfig:
    """All tunables. No literal appears in decision logic."""

    risk_target: float = 0.02  # max tolerated error rate among auto-merges
    risk_ci_z: float = 1.96  # z for the upper risk bound (conservative tau)
    # calibrator-health floors
    min_calibration_n: int = 200
    max_ece: float = 0.05
    min_auroc: float = 0.65  # < this: confidence doesn't rank correctness
    max_bin_ci_width: float = 0.20
    # per-decision conservatism
    wilson_floor: float = 0.90  # Wilson-lower of the bin accuracy must clear this
    wilson_z: float = 1.96
    protected_auto_merge: bool = False  # keep False; True reopens the Goodhart hole


@dataclass(frozen=True)
class CalibratorHealth:
    n: int
    ece: float
    auroc: float
    bin_ci_width: float

    def is_trustworthy(self, cfg: GatePolicyConfig) -> bool:
        return (
            self.n >= cfg.min_calibration_n
            and self.ece <= cfg.max_ece
            and self.auroc >= cfg.min_auroc
            and self.bin_ci_width <= cfg.max_bin_ci_width
        )


@runtime_checkable
class Calibrator(Protocol):
    """Matches agent_core's Calibrator protocol (temperature / isotonic / binning)."""

    def predict(self, raw_score: float) -> float: ...


@dataclass(frozen=True)
class ChangeContext:
    mech_pass: bool  # regression gate: no net-new ruff/pytest findings (FULL suite)
    touches_protected: bool  # from eval_protected_paths.py
    raw_confidence: float  # agent self-reported, in [0, 1]
    domain: str


def _wilson_bound(successes: int, n: int, z: float, *, lower: bool) -> float:
    """Wilson lower/upper bound, delegating to agent_core.calibration."""
    lo, hi = wilson_interval(successes, n, z)
    return lo if lower else hi


def threshold_for_risk(
    scores: Sequence[float],
    correct: Sequence[bool],
    cfg: GatePolicyConfig,
) -> float | None:
    """Smallest tau whose UPPER risk bound on auto-merges <= risk_target.

    Should be evaluated on a held-out fold (not the calibrator-fit fold) to avoid
    overfitting the threshold. Returns ``None`` if no threshold achieves the risk
    target — the domain is then simply not yet eligible for auto-merge.
    """
    if not scores:
        return None
    candidates = sorted(set(scores))
    for tau in candidates:  # ascending: first pass = smallest tau = max coverage
        # tau is drawn from scores, so at least the elements == tau are kept;
        # _wilson_bound also handles n == 0 safely if that ever changes.
        kept = [c for s, c in zip(scores, correct, strict=True) if s >= tau]
        acc_lower = _wilson_bound(sum(kept), len(kept), cfg.risk_ci_z, lower=True)
        risk_upper = 1.0 - acc_lower
        if risk_upper <= cfg.risk_target:
            return tau
    return None


def decide(
    ctx: ChangeContext,
    calibrator: Calibrator | None,
    health: CalibratorHealth | None,
    tau: float | None,
    bin_successes: int,
    bin_n: int,
    cfg: GatePolicyConfig,
) -> GateDecision:
    """Decide MERGE / ESCALATE / REJECT.

    ``bin_successes``/``bin_n`` are the calibration-bin counts at the operating
    point ``calibrator.predict(ctx.raw_confidence)`` falls in; they back the
    conservative Wilson floor so a high point-estimate on thin data cannot merge.
    """
    # Layer 0 — mechanical ground truth. Non-negotiable.
    if not ctx.mech_pass:
        return GateDecision.REJECT

    # Layer 1 — protected eval-defining paths.
    if ctx.touches_protected and not cfg.protected_auto_merge:
        return GateDecision.ESCALATE

    # Layer 2 — calibrated trust. Trust the number only if it is trustworthy.
    if calibrator is None or health is None or tau is None:
        return GateDecision.ESCALATE
    if not health.is_trustworthy(cfg):
        return GateDecision.ESCALATE

    p = calibrator.predict(ctx.raw_confidence)
    if p < tau:
        return GateDecision.ESCALATE

    # Conservative floor: the bin's Wilson-lower accuracy must clear the floor.
    if _wilson_bound(bin_successes, bin_n, cfg.wilson_z, lower=True) < cfg.wilson_floor:
        return GateDecision.ESCALATE

    return GateDecision.AUTO_MERGE

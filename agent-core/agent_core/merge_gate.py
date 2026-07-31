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
  * Calibration is only trusted when the calibrator is healthy: enough held-out
    samples, low ECE, AUROC that actually rank-orders correctness, and a tight CI
    *in the region that can actually auto-merge* -- or, if that region holds no
    evidence at all, no auto-merge. An unmeasurable floor is not a satisfied one.

Pure and deterministic: every tunable lives on :class:`GatePolicyConfig`; no
literal appears in decision logic. The Wilson math is reused from
:mod:`agent_core.calibration` rather than re-implemented.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from .calibration import DEFAULT_N_BINS, wilson_interval
from .config import ConfigError


class GateDecision(str, Enum):
    AUTO_MERGE = "auto_merge"
    ESCALATE = "escalate"  # human (or higher-authority agent) review
    REJECT = "reject"  # mechanical ground-truth failure


def _require_finite_in(
    name: str,
    value: float,
    lo: float,
    hi: float,
    *,
    lo_inclusive: bool = True,
    hi_inclusive: bool = True,
    why: str = "",
) -> None:
    """Reject ``value`` unless finite and within the (in/ex)clusive ``lo``/``hi`` bounds.

    Kept as a helper rather than nine inline ``if``s so ``__post_init__`` stays a flat, low
    -complexity sequence (the mccabe budget is 14) and the interval notation in the message
    is generated rather than hand-duplicated per field. The ``math.isfinite`` guard is not
    redundant: ``NaN`` compares False against every bound, so an unguarded range test would
    *pass* it -- the exact one-sided fail-open this subsystem has already been bitten by in
    ``ChangeContext`` and ``BinningCalibrator.bin_index``.
    """
    ok = math.isfinite(value)
    ok = ok and (lo <= value if lo_inclusive else lo < value)
    ok = ok and (value <= hi if hi_inclusive else value < hi)
    if not ok:
        left, right = ("[" if lo_inclusive else "("), ("]" if hi_inclusive else ")")
        detail = f" -- {why}" if why else ""
        raise ConfigError(
            f"merge-gate.{name} must be a finite value in {left}{lo}, {hi}{right}"
            f"{detail} (got {value!r})"
        )


@dataclass(frozen=True)
class GatePolicyConfig:
    """All tunables. No literal appears in decision logic.

    Every bound below follows one rule: **reject the vacuous endpoint, allow the maximally
    strict one.** A threshold that can never reject anything is a lie about the presence of a
    check -- worse than no field at all, because the audit log then reports a floor that did
    no work. A threshold that can never *accept* anything is merely a kill switch, which is
    safe and occasionally what an operator wants.
    """

    risk_target: float = 0.02  # max tolerated error rate among auto-merges
    risk_ci_z: float = 1.96  # z for the upper risk bound (conservative tau)
    # calibrator-health floors
    min_calibration_n: int = 200
    max_ece: float = 0.05
    min_auroc: float = 0.65  # < this: confidence doesn't rank correctness
    max_bin_ci_width: float = 0.20
    # Bin count for the calibrator, its ECE, and the operating-region CI. On the policy
    # (not just as a library default) so the three cannot drift apart, and so retuning it
    # is an operator decision rather than a source edit -- ADR 0005 SS3.
    n_bins: int = DEFAULT_N_BINS
    # per-decision conservatism
    wilson_floor: float = 0.90  # Wilson-lower of the bin accuracy must clear this
    wilson_z: float = 1.96
    # Keep False; True reopens the Goodhart hole. Deliberately NOT validated and deliberately
    # NOT exposed as a CLI flag: rejecting True would delete an escape hatch ADR 0005 documents
    # and the suite exercises, while a flag would hand CI a knob that disables the protected
    # -path layer. Reachable in-process, unreachable from an operator; `merge_gate_ci.run`
    # logs a warning if it is ever set.
    protected_auto_merge: bool = False

    def __post_init__(self) -> None:
        _require_finite_in(
            "risk_target",
            self.risk_target,
            0.0,
            1.0,
            hi_inclusive=False,
            why="1.0 tolerates every error, collapsing tau to the smallest observed score",
        )
        _require_finite_in("risk_ci_z", self.risk_ci_z, 0.0, math.inf, lo_inclusive=False)
        if self.min_calibration_n < 1:
            raise ConfigError(
                "merge-gate.min_calibration_n must be >= 1 -- 0 is not a floor but the "
                f"absence of one (got {self.min_calibration_n!r})"
            )
        _require_finite_in("max_ece", self.max_ece, 0.0, 1.0, hi_inclusive=False)
        _require_finite_in(
            "min_auroc",
            self.min_auroc,
            0.5,
            1.0,
            lo_inclusive=False,
            why="at or below 0.5 the single-class AUROC sentinel would pass the health floor",
        )
        _require_finite_in("max_bin_ci_width", self.max_bin_ci_width, 0.0, 1.0, hi_inclusive=False)
        _require_finite_in("wilson_floor", self.wilson_floor, 0.0, 1.0, lo_inclusive=False)
        _require_finite_in("wilson_z", self.wilson_z, 0.0, math.inf, lo_inclusive=False)
        if self.n_bins < 2:
            raise ConfigError(
                "merge-gate.n_bins must be >= 2 -- a single bin makes predict() a constant, "
                "tau equal to that constant, and every change clear the threshold "
                f"(got {self.n_bins!r})"
            )


@dataclass(frozen=True)
class CalibratorHealth:
    n: int
    ece: float
    auroc: float
    # ``None`` means UNMEASURABLE: no calibrator bin could ever be an operating point, so
    # there is no interval to be tight. Deliberately not NaN or ``inf``: NaN compares False
    # against every bound, which is the one-sided fail-open this subsystem has already been
    # bitten by twice, and ``inf`` would conflate "not measured" with "measured as
    # maximally wide". ``None`` is checked by mypy at every use site.
    bin_ci_width: float | None

    def is_trustworthy(self, cfg: GatePolicyConfig) -> bool:
        return (
            self.n >= cfg.min_calibration_n
            and self.ece <= cfg.max_ece
            and self.auroc >= cfg.min_auroc
            and self.bin_ci_width is not None  # unmeasurable is not tight
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

    def __post_init__(self) -> None:
        """Enforce the ``[0, 1]`` contract that the field comment has always claimed.

        This is a fail-closed boundary, not a formality. ``NaN`` compares False against
        every edge, so an unvalidated ``NaN`` fell through the bin scan to the *top*
        bin -- the highest-confidence bucket -- and could reach AUTO_MERGE; so could any
        value above 1.0. Out-of-range low values escalated, so the failure was one-sided
        toward unsafe. Reject at construction instead: a confidence we cannot interpret
        must never read as maximum confidence.
        """
        if not math.isfinite(self.raw_confidence):
            raise ValueError(
                f"raw_confidence must be a finite number in [0, 1] (got {self.raw_confidence!r})"
            )
        if not 0.0 <= self.raw_confidence <= 1.0:
            raise ValueError(f"raw_confidence must be in [0, 1] (got {self.raw_confidence!r})")


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

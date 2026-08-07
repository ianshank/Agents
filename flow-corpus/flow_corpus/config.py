"""Corpus configuration — frozen dataclasses, no hardcoded values at call sites.

Mirrors :mod:`agent_core.config`: every threshold the corpus gates on lives here as
a typed field with a default, overridable by construction. The indeterminate-rate
cap is *derived* (``audit_capacity / corpus_volume``) rather than stored, per the
spec's no-hardcoded-values rule.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _require_finite(name: str, value: float) -> None:
    """Reject NaN and infinity before any comparison is attempted.

    Every comparison against NaN is False, so a NaN passes *every* range check below
    untouched and silently deletes whatever floor it was configured as. Reproduced
    before this guard existed: ``power_min_sample=nan`` made ``is_directional_only``
    return False for any n, so an under-powered sample stopped being directional-only
    and became gate-eligible.

    ``CorpusConfig`` is constructed directly *and* built by
    ``BRConfig.as_corpus_config()``, so the same field is reachable from two packages
    and needs the guard in both (``behavioral_regression.config`` carries the mirror).
    """
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")


def _require_positive(name: str, value: float) -> None:
    """Reject ``value`` unless strictly greater than zero."""
    _require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be > 0 (got {value!r})")


def _require_at_least(name: str, value: float, bound: float) -> None:
    """Reject ``value`` unless greater than or equal to ``bound``."""
    _require_finite(name, value)
    if value < bound:
        raise ValueError(f"{name} must be >= {bound} (got {value!r})")


def _require_in_range(
    name: str,
    value: float,
    lo: float,
    hi: float,
    *,
    lo_inclusive: bool = True,
    hi_inclusive: bool = True,
) -> None:
    """Reject ``value`` unless it lies within the (in/ex)clusive bounds.

    Mirrors ``behavioral_regression.config._require_in_range`` including its interval
    notation, so an operator sees the same message shape from either package. The two
    cannot be shared directly: ``flow_corpus`` and ``behavioral_regression`` may both
    depend on ``agent_core`` but not on each other, and ``agent_core`` is deliberately
    dependency-free — a shared home would mean a new declared edge for four validators.
    """
    _require_finite(name, value)
    lo_ok = lo <= value if lo_inclusive else lo < value
    hi_ok = value <= hi if hi_inclusive else value < hi
    if not (lo_ok and hi_ok):
        left = "[" if lo_inclusive else "("
        right = "]" if hi_inclusive else ")"
        raise ValueError(f"{name} must be in {left}{lo}, {hi}{right} (got {value!r})")


@dataclass(frozen=True)
class CorpusConfig:
    # --- task-suite power -----------------------------------------------------
    declared_n_per_domain: int = 200
    """Declared instances per domain. Calibration power is declared, not guessed."""

    power_min_sample: int = 100
    """Below this many resolved outcomes, a metric is *directional only* and cannot gate."""

    # --- oracle validation ----------------------------------------------------
    min_oracle_kappa: float = 0.8
    """Cohen's κ vs human audit an oracle tier must clear before its verdicts may gate."""

    # --- discrimination canary ------------------------------------------------
    min_canary_margin: float = 0.5
    """Required separation (Wilson-bounded pass-rate gap) between gold and no-op agents."""

    # --- calibration gate -----------------------------------------------------
    max_brier_reliability: float = 0.1
    """Primary gate: Brier reliability term must be at or below this (lower is better)."""

    n_bins: int = 10
    """Bin count for the Brier (Murphy) decomposition."""

    rotation_stability_threshold: float = 0.05
    """Max allowed spread (max-min) in Brier reliability across holdout rotations."""

    wilson_z: float = 1.96
    """z for Wilson intervals (1.96 ≈ 95%)."""

    # --- holdout / cross-check partition --------------------------------------
    holdout_fit_fraction: float = 0.5
    """Fraction of instances on the fit/seen side of the holdout & cross-check split."""

    # --- bootstrap (significance of metric deltas) ----------------------------
    bootstrap_resamples: int = 2000
    """Default resample count for bootstrap CIs (e.g. the confidence cross-check)."""

    bootstrap_alpha: float = 0.05
    """Two-sided alpha for bootstrap CIs (0.05 ≈ 95% interval)."""

    # --- audit budget (derives the indeterminate cap) -------------------------
    audit_capacity_per_cycle: int = 30
    """Human-audit labels affordable per cycle (the scarce resource)."""

    corpus_volume_per_cycle: int = 200
    """Total instances judged per cycle."""

    def __post_init__(self) -> None:
        """Validate every gating threshold.

        Each guard delegates to a shared validator so the finite-value check lives in
        one place per package rather than being repeated inline nine times — the
        duplication that let NaN through in the first place.
        """
        _require_positive("declared_n_per_domain", self.declared_n_per_domain)
        _require_positive("power_min_sample", self.power_min_sample)
        _require_positive("corpus_volume_per_cycle", self.corpus_volume_per_cycle)
        _require_at_least("audit_capacity_per_cycle", self.audit_capacity_per_cycle, 0)
        _require_in_range("min_oracle_kappa", self.min_oracle_kappa, 0.0, 1.0)
        _require_at_least("n_bins", self.n_bins, 1)
        _require_in_range(
            "holdout_fit_fraction",
            self.holdout_fit_fraction,
            0.0,
            1.0,
            lo_inclusive=False,
            hi_inclusive=False,
        )
        _require_at_least("bootstrap_resamples", self.bootstrap_resamples, 1)
        _require_in_range(
            "bootstrap_alpha",
            self.bootstrap_alpha,
            0.0,
            1.0,
            lo_inclusive=False,
            hi_inclusive=False,
        )
        # The four fields below carried no guard at all, so a NaN threshold reached the
        # gates. Only the finite check is added for the first three: their valid ranges
        # differ per gate and inventing bounds here would reject configs that work today.
        _require_finite("max_brier_reliability", self.max_brier_reliability)
        _require_finite("min_canary_margin", self.min_canary_margin)
        _require_finite("rotation_stability_threshold", self.rotation_stability_threshold)
        # wilson_z is the exception: every other home for this same field already requires
        # it positive (behavioral_regression.config, agent_core.config,
        # eval_harness.config.models' `gt=0`), and a non-positive z makes
        # canary.separation's interval degenerate. flow_corpus was the lone gap.
        _require_positive("wilson_z", self.wilson_z)

    @property
    def max_indeterminate_rate(self) -> float:
        """Derived cap: indeterminates must fit within the human-audit budget.

        If more than this fraction abstains, the oracle domain is too weak — there
        is not enough audit capacity to resolve the indeterminates.
        """
        return self.audit_capacity_per_cycle / self.corpus_volume_per_cycle

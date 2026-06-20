"""Corpus configuration — frozen dataclasses, no hardcoded values at call sites.

Mirrors :mod:`agent_core.config`: every threshold the corpus gates on lives here as
a typed field with a default, overridable by construction. The indeterminate-rate
cap is *derived* (``audit_capacity / corpus_volume``) rather than stored, per the
spec's no-hardcoded-values rule.
"""

from __future__ import annotations

from dataclasses import dataclass


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

    # --- audit budget (derives the indeterminate cap) -------------------------
    audit_capacity_per_cycle: int = 30
    """Human-audit labels affordable per cycle (the scarce resource)."""

    corpus_volume_per_cycle: int = 200
    """Total instances judged per cycle."""

    def __post_init__(self) -> None:
        if self.declared_n_per_domain <= 0:
            raise ValueError("declared_n_per_domain must be > 0")
        if self.power_min_sample <= 0:
            raise ValueError("power_min_sample must be > 0")
        if self.corpus_volume_per_cycle <= 0:
            raise ValueError("corpus_volume_per_cycle must be > 0")
        if self.audit_capacity_per_cycle < 0:
            raise ValueError("audit_capacity_per_cycle must be >= 0")
        if not 0.0 <= self.min_oracle_kappa <= 1.0:
            raise ValueError("min_oracle_kappa must be in [0, 1]")
        if self.n_bins < 1:
            raise ValueError("n_bins must be >= 1")

    @property
    def max_indeterminate_rate(self) -> float:
        """Derived cap: indeterminates must fit within the human-audit budget.

        If more than this fraction abstains, the oracle domain is too weak — there
        is not enough audit capacity to resolve the indeterminates.
        """
        return self.audit_capacity_per_cycle / self.corpus_volume_per_cycle

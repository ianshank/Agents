"""CorpusConfig validation + derived indeterminate cap."""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from flow_corpus.config import CorpusConfig
from flow_corpus.validation.power import is_directional_only


def test_derived_indeterminate_rate() -> None:
    cfg = CorpusConfig(audit_capacity_per_cycle=30, corpus_volume_per_cycle=200)
    assert cfg.max_indeterminate_rate == pytest.approx(0.15)


def test_derived_rate_is_not_stored_literal() -> None:
    # Changing the budget changes the cap (it is derived, not hardcoded).
    a = CorpusConfig(audit_capacity_per_cycle=10, corpus_volume_per_cycle=100)
    b = CorpusConfig(audit_capacity_per_cycle=50, corpus_volume_per_cycle=100)
    assert a.max_indeterminate_rate == pytest.approx(0.1)
    assert b.max_indeterminate_rate == pytest.approx(0.5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"declared_n_per_domain": 0},
        {"power_min_sample": 0},
        {"corpus_volume_per_cycle": 0},
        {"audit_capacity_per_cycle": -1},
        {"min_oracle_kappa": 1.5},
        {"n_bins": 0},
        {"holdout_fit_fraction": 0.0},
        {"holdout_fit_fraction": 1.0},
        {"bootstrap_resamples": 0},
        {"bootstrap_alpha": 0.0},
        {"bootstrap_alpha": 1.0},
    ],
)
def test_invalid_config_rejected(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CorpusConfig(**kwargs)


def test_non_positive_wilson_z_rejected() -> None:
    """Harmonised with every other home for this field (behavioral_regression.config,
    agent_core.config, eval_harness.config.models' ``gt=0``); flow_corpus was the gap.
    A non-positive z makes ``canary.separation``'s Wilson interval degenerate.
    """
    with pytest.raises(ValueError, match="wilson_z must be > 0"):
        CorpusConfig(wilson_z=0.0)


# --- non-finite thresholds ----------------------------------------------------------
#
# Every comparison against NaN is False, so before ``_require_finite`` a NaN passed all
# of the range checks untouched and silently deleted the floor it was configured as.
# ``CorpusConfig`` is reachable directly *and* via ``BRConfig.as_corpus_config()``, so
# the guard is needed on this side too — see behavioral-regression/tests/test_config.py.

NON_FINITE = (float("nan"), float("inf"), float("-inf"))

#: Derived from the dataclass rather than listed, so a threshold added later is covered
#: automatically — an unguarded new field fails this test instead of shipping.
GUARDED_FIELDS = tuple(f.name for f in fields(CorpusConfig))


def _build(**overrides: Any) -> CorpusConfig:
    """Construct a config from untyped keyword values.

    Several guarded fields are annotated ``int`` (``power_min_sample``,
    ``declared_n_per_domain``, ``n_bins``, the two audit-budget counts), so a literal
    ``power_min_sample=float("nan")`` is a static type error. That annotation is exactly
    what does *not* hold at runtime — these values arrive from config files and from
    ``BRConfig.as_corpus_config()``, where nothing enforces it — which is why the runtime
    guard has to exist. ``**kwargs`` reproduces that untyped path rather than silencing the
    checker with ``type: ignore`` comments that would also hide a real error later.
    """
    return CorpusConfig(**overrides)


@pytest.mark.parametrize("field_name", GUARDED_FIELDS)
@pytest.mark.parametrize("value", NON_FINITE, ids=("nan", "inf", "-inf"))
def test_every_threshold_rejects_non_finite(field_name: str, value: float) -> None:
    """No field may accept NaN or infinity — including any field added after this test."""
    with pytest.raises(ValueError, match="must be a finite number"):
        _build(**{field_name: value})


def test_non_finite_error_names_the_offending_value() -> None:
    with pytest.raises(ValueError, match=r"power_min_sample must be a finite number \(got nan\)"):
        _build(power_min_sample=float("nan"))


def test_nan_power_floor_cannot_flip_the_directional_only_decision() -> None:
    """The regression this guard exists for, asserted at the decision it corrupted.

    ``is_directional_only(30, nan)`` evaluates ``30 < nan`` -> False, so an under-powered
    sample stopped being directional-only and became gate-eligible. The κ-gate, the
    reliability report and the confidence cross-check all route through that one call.
    """
    # Typed Any deliberately: the annotation says int, and the whole point is that the
    # annotation was not enforced at runtime, so an unvalidated config carried this through.
    unenforced: Any = float("nan")
    assert is_directional_only(30, CorpusConfig().power_min_sample) is True
    assert is_directional_only(30, unenforced) is False  # why the config guard is load-bearing
    with pytest.raises(ValueError):
        _build(power_min_sample=float("nan"))


def test_derived_indeterminate_cap_cannot_be_non_finite() -> None:
    """The derived cap has no guard of its own; it inherits both operands' finiteness."""
    for value in NON_FINITE:
        with pytest.raises(ValueError):
            _build(audit_capacity_per_cycle=value)
        with pytest.raises(ValueError):
            _build(corpus_volume_per_cycle=value)


def test_finite_thresholds_still_construct() -> None:
    """Backwards compatibility: the guard rejects only values that were always invalid."""
    assert CorpusConfig().power_min_sample == 100
    assert CorpusConfig(wilson_z=2.58, min_canary_margin=0.75).wilson_z == 2.58

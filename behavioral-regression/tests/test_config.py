from __future__ import annotations

from typing import Any

import pytest
from flow_corpus.validation.power import is_directional_only

from behavioral_regression.config import BRConfig, ConfigError
from behavioral_regression.version import SCHEMA_VERSION


def test_defaults_valid_and_roundtrip():
    cfg = BRConfig()
    assert cfg.version == SCHEMA_VERSION
    assert BRConfig.from_dict(cfg.to_dict()) == cfg


def test_as_corpus_config_carries_fields():
    cfg = BRConfig(min_judge_kappa=0.7, power_min_sample=42, min_canary_margin=0.4)
    cc = cfg.as_corpus_config()
    assert cc.min_oracle_kappa == 0.7
    assert cc.power_min_sample == 42
    assert cc.min_canary_margin == 0.4
    assert cc.n_bins == cfg.n_bins


def test_from_dict_rejects_unknown_keys():
    data = BRConfig().to_dict()
    data["bogus"] = 1
    with pytest.raises(ConfigError, match="unknown config keys"):
        BRConfig.from_dict(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_pairs": 0},
        {"v1_sycophancy_mean": 1.5},
        {"v2_sycophancy_mean": -0.1},
        {"dist_sigma": 0.0},
        {"injected_shift": 0.0},
        {"judge_noise": 1.0},
        {"judge_bias": 2.0},
        {"judge_indeterminate_band": 1.0},
        {"min_judge_kappa": 1.5},
        {"power_min_sample": 0},
        {"n_bins": 0},
        {"wilson_z": 0.0},
        {"bootstrap_resamples": 0},
        {"bootstrap_alpha": 0.0},
        {"max_brier_reliability": 1.5},
        {"ship_risk_target": 0.0},
        {"min_canary_margin": 0.0},
    ],
)
def test_invalid_fields_raise(kwargs):
    with pytest.raises(ConfigError):
        BRConfig(**kwargs)


# --- non-finite thresholds ----------------------------------------------------------
#
# Every comparison against NaN is False, so before the ``_require_finite`` guard a NaN
# passed *all* three shared validators untouched and silently deleted whatever floor it
# was configured as. Infinity is the mirror image: it clears every ``> 0`` check.

NON_FINITE = (float("nan"), float("inf"), float("-inf"))

#: Derived from the dataclass rather than listed, so a field added later is covered
#: automatically — an unguarded new threshold fails this test instead of shipping.
GUARDED_FIELDS = tuple(f for f in BRConfig().to_dict() if f != "version")


def _build(**overrides: Any) -> BRConfig:
    """Construct a config from untyped keyword values.

    Several guarded fields are annotated ``int`` (``power_min_sample``, ``n_pairs``,
    ``n_bins``, ``bootstrap_resamples``), so a literal ``power_min_sample=float("nan")``
    is a static type error. That annotation is exactly what does *not* hold at runtime:
    these values arrive from JSON config files and ``--set`` overrides, where nothing
    enforces it — which is why the runtime guard has to exist. Routing through ``**kwargs``
    reproduces that untyped path honestly, rather than silencing the checker with
    ``type: ignore`` comments that would also hide a real error later.
    """
    return BRConfig(**overrides)


@pytest.mark.parametrize("field", GUARDED_FIELDS)
@pytest.mark.parametrize("value", NON_FINITE, ids=("nan", "inf", "-inf"))
def test_every_threshold_rejects_non_finite(field: str, value: float) -> None:
    """No field may accept NaN or infinity — including any field added after this test."""
    with pytest.raises(ConfigError, match="must be a finite number"):
        _build(**{field: value})


def test_non_finite_error_names_the_offending_value():
    with pytest.raises(ConfigError, match=r"power_min_sample must be a finite number \(got nan\)"):
        _build(power_min_sample=float("nan"))


def test_nan_power_floor_cannot_flip_the_directional_only_decision():
    """The regression this guard exists for, asserted at the decision it corrupted.

    With ``power_min_sample=nan``, ``is_directional_only(30, nan)`` evaluates ``30 < nan``
    -> False: a 30-pair sample stopped being directional-only and became gate-eligible,
    turning an honest ESCALATE into a real ship/no-ship decision on data far below the
    declared power floor. The config can no longer be built, so the flip is unreachable.
    """
    # Typed Any deliberately: the annotation says int, and the whole point is that the
    # annotation was not enforced at runtime, so an unvalidated config carried this through.
    unenforced: Any = float("nan")
    assert is_directional_only(30, BRConfig().power_min_sample) is True
    assert is_directional_only(30, unenforced) is False  # why the config guard is load-bearing
    with pytest.raises(ConfigError):
        _build(power_min_sample=float("nan"))


def test_as_corpus_config_cannot_carry_a_non_finite_floor():
    """``as_corpus_config`` is the cross-package path; the floor is guarded on both sides."""
    for value in NON_FINITE:
        with pytest.raises(ConfigError):
            _build(power_min_sample=value).as_corpus_config()


def test_from_dict_rejects_non_finite():
    """The dict path (config files, ``--set`` overrides) runs the same validation."""
    data = BRConfig().to_dict()
    data["min_canary_margin"] = float("inf")
    with pytest.raises(ConfigError, match="must be a finite number"):
        BRConfig.from_dict(data)


def test_finite_thresholds_still_construct():
    """Backwards compatibility: the guard rejects only values that were always invalid."""
    assert BRConfig().power_min_sample == 100
    assert BRConfig(power_min_sample=1, wilson_z=2.58).wilson_z == 2.58

from __future__ import annotations

import pytest

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

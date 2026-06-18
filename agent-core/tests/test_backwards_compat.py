import pytest

import agent_core
from agent_core import FrameworkConfig, expected_calibration_error
from agent_core.version import migrate_config


def test_migrates_v1_0_0_renamed_keys():
    old = {"version": "1.0.0", "budget": {"budget_cap": 1000.0, "reserve": 0.1}}
    cfg = FrameworkConfig.from_dict(old)
    assert cfg.budget.cap_units == 1000.0
    assert cfg.budget.reserve_fraction == 0.1
    assert cfg.version == agent_core.SCHEMA_VERSION


def test_current_version_is_noop():
    data = {"version": agent_core.SCHEMA_VERSION, "loop": {"max_cycles": 7}}
    assert migrate_config(data)["loop"]["max_cycles"] == 7


def test_unknown_version_has_no_path():
    with pytest.raises(ValueError):
        migrate_config({"version": "0.0.1"})


def test_deprecated_alias_still_works_with_warning():
    probs = [0.9] * 10 + [0.6] * 10
    outcomes = [1] * 7 + [0] * 3 + [1] * 6 + [0] * 4
    with pytest.warns(DeprecationWarning):
        legacy = agent_core.ece(probs, outcomes, n_bins=10)
    assert legacy == expected_calibration_error(probs, outcomes, n_bins=10)


def test_ece_deprecation_warning_names_old_symbol() -> None:
    """The deprecation warning must say 'ece' is deprecated, not the new name."""
    with pytest.warns(DeprecationWarning, match="'ece' is deprecated"):
        agent_core.ece([0.9, 0.1], [1, 0], n_bins=2)


def test_migrates_1_1_0_to_1_2_0() -> None:
    """A 1.1.0 config migrates to 1.2.0 with all new sections defaulted."""
    from agent_core import AsyncConfig, GoldenConfig, RecalibrationConfig, SanitizerConfig

    old = {"version": "1.1.0", "loop": {"max_cycles": 7}}
    cfg = FrameworkConfig.from_dict(old)
    assert cfg.loop.max_cycles == 7
    assert cfg.version == agent_core.SCHEMA_VERSION
    assert cfg.sanitizer == SanitizerConfig()
    assert cfg.golden == GoldenConfig()
    assert cfg.recalibration == RecalibrationConfig()
    assert cfg.async_exec == AsyncConfig()


def test_full_chain_1_0_0_to_1_2_0() -> None:
    """1.0.0 config with renamed budget keys passes through the full 1.0.0→1.1.0→1.2.0 chain."""
    old = {
        "version": "1.0.0",
        "budget": {"budget_cap": 1000.0, "reserve": 0.1},
        "golden": {"train_ratio": 0.5, "calibration_ratio": 0.25, "test_ratio": 0.25},
    }
    cfg = FrameworkConfig.from_dict(old)
    assert cfg.budget.cap_units == 1000.0
    assert cfg.budget.reserve_fraction == 0.1
    assert cfg.golden.train_ratio == 0.5
    assert cfg.version == agent_core.SCHEMA_VERSION


def test_decoupled_versions_contract() -> None:
    """__version__ (package) and SCHEMA_VERSION (config schema) are independent versioning axes."""
    from agent_core.version import SCHEMA_VERSION, __version__

    assert isinstance(__version__, str) and __version__
    assert isinstance(SCHEMA_VERSION, str) and SCHEMA_VERSION
    assert __version__ == "1.2.0"
    assert SCHEMA_VERSION == "1.2.0"

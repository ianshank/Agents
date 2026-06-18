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

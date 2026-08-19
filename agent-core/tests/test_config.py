import math

import pytest

from agent_core import (
    BudgetConfig,
    CalibrationConfig,
    ConfigError,
    FrameworkConfig,
    LoopConfig,
    ProbeConfig,
)


def test_defaults_and_derived_values():
    cfg = FrameworkConfig()
    assert cfg.budget.cap_units == 600_000.0
    assert math.isclose(cfg.reserve_units, 90_000.0)
    assert math.isclose(cfg.loop_ceiling_units, 510_000.0)


def test_round_trip_to_from_dict():
    cfg = FrameworkConfig()
    restored = FrameworkConfig.from_dict(cfg.to_dict())
    assert restored.budget == cfg.budget
    assert restored.loop == cfg.loop
    assert restored.calibration == cfg.calibration
    assert restored.logging == cfg.logging


@pytest.mark.parametrize(
    "factory",
    [
        lambda: BudgetConfig(cap_units=0),
        lambda: BudgetConfig(reserve_fraction=1.0),
        lambda: BudgetConfig(reserve_fraction=-0.1),
        lambda: LoopConfig(max_cycles=0),
        lambda: LoopConfig(convergence_epsilon=0),
        lambda: CalibrationConfig(n_bins=0),
        lambda: CalibrationConfig(auroc_target=1.5),
        lambda: CalibrationConfig(wilson_z=0),
        lambda: CalibrationConfig(min_eval_samples=0),
        lambda: CalibrationConfig(min_eval_samples=-1),
        lambda: ProbeConfig(wilson_z=0),
        lambda: ProbeConfig(order_flip_tolerance=-0.1),
        lambda: ProbeConfig(order_flip_tolerance=1.1),
        lambda: ProbeConfig(verbosity_delta_tolerance=-0.1),
        lambda: ProbeConfig(self_preference_tolerance=1.1),
        lambda: ProbeConfig(min_pairs=0),
    ],
)
def test_invalid_values_raise(factory):
    with pytest.raises(ConfigError):
        factory()


def test_probe_config_round_trips_through_framework_config():
    cfg = FrameworkConfig(probe=ProbeConfig(order_flip_tolerance=0.2))
    restored = FrameworkConfig.from_dict(cfg.to_dict())
    assert restored.probe == cfg.probe


def test_calibration_guard_defaults_are_a_no_op():
    """Defaults must reproduce the pre-guard gate semantics, so adding the fields
    cannot change any existing caller's verdict."""
    cfg = CalibrationConfig()
    assert cfg.min_eval_samples == 1  # `_check_pairs` already rejects empty input
    assert cfg.require_discrimination is False


def test_calibration_config_predating_guards_still_loads():
    """A config persisted before the guard fields existed must migrate to the defaults."""
    legacy = {
        "n_bins": 10,
        "ece_target": 0.05,
        "mce_target": 0.12,
        "auroc_target": 0.80,
        "wilson_z": 1.96,
    }
    cfg = FrameworkConfig.from_dict({"calibration": legacy})
    assert cfg.calibration.min_eval_samples == 1
    assert cfg.calibration.require_discrimination is False
    assert FrameworkConfig.from_dict(cfg.to_dict()).calibration == cfg.calibration


def test_unknown_key_rejected():
    with pytest.raises(ConfigError):
        FrameworkConfig.from_dict({"budget": {}, "mystery": 1})


def test_partial_override_uses_defaults_elsewhere():
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 9}})
    assert cfg.loop.max_cycles == 9
    assert cfg.budget == BudgetConfig()  # untouched section keeps defaults


def test_from_dict_invalid_section_value_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        FrameworkConfig.from_dict({"loop": {"max_cycles": "not_an_int"}})


def test_from_dict_null_section_value_uses_default() -> None:
    """Explicit null for a known section must not be treated as an unknown key."""
    cfg = FrameworkConfig.from_dict({"budget": None})
    assert cfg.budget == BudgetConfig()


def test_from_dict_unknown_nested_key_raises() -> None:
    """Unknown keys inside a known section must raise ConfigError (via TypeError)."""
    with pytest.raises(ConfigError):
        FrameworkConfig.from_dict({"budget": {"unknown_key": 1}})


def test_from_dict_bad_section_type_raises() -> None:
    """Passing a non-dict value for a known section must raise ConfigError."""
    with pytest.raises(ConfigError):
        FrameworkConfig.from_dict({"budget": 42})

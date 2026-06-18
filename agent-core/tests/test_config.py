import math

import pytest

from agent_core import (
    BudgetConfig,
    CalibrationConfig,
    ConfigError,
    FrameworkConfig,
    LoopConfig,
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
    ],
)
def test_invalid_values_raise(factory):
    with pytest.raises(ConfigError):
        factory()


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

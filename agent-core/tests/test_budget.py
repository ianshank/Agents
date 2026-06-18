import math

import pytest

from agent_core import BudgetLedger, FrameworkConfig


def _ledger(cap=1000.0, reserve_fraction=0.2):
    cfg = FrameworkConfig.from_dict(
        {"budget": {"cap_units": cap, "reserve_fraction": reserve_fraction}}
    )
    return BudgetLedger(cfg)


def test_ceiling_and_reserve_derivation():
    led = _ledger(cap=1000.0, reserve_fraction=0.2)
    assert math.isclose(led.reserve, 200.0)
    assert math.isclose(led.ceiling, 800.0)
    assert led.spent == 0.0


def test_can_admit_boundary_is_inclusive():
    led = _ledger(cap=1000.0, reserve_fraction=0.2)  # ceiling 800
    led.record(700.0)
    assert led.can_admit(100.0) is True   # 700 + 100 == 800, fits
    assert led.can_admit(100.01) is False


def test_record_accumulates_and_never_touches_reserve():
    led = _ledger(cap=1000.0, reserve_fraction=0.2)
    led.record(300.0)
    led.record(150.0)
    assert math.isclose(led.spent, 450.0)
    assert math.isclose(led.reserve, 200.0)       # reserve unchanged
    assert math.isclose(led.remaining_for_loop, 350.0)  # 800 - 450


def test_negative_inputs_rejected():
    led = _ledger()
    with pytest.raises(ValueError):
        led.record(-1.0)
    with pytest.raises(ValueError):
        led.can_admit(-1.0)

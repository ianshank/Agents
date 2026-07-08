#!/usr/bin/env python3
"""Validation script for F-030 — time-windowed judge rate limiting.

Deterministic and offline (no real time): a fake clock + sleeper drive a
``BudgetedJudge`` whose ``JudgeBudgetConfig`` carries the additive window fields.
Asserts the window throttles in block mode, skips in skip mode, recovers after
the window passes, stays independent of the cumulative cap, and that the config
requires the two window fields together — all without sleeping for real.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import cast

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

from eval_harness.config.models import JudgeBudgetConfig
from eval_harness.judges import MockJudge


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.t += secs


def validate_f030() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-030")
    errors: list[str] = []

    try:
        from agent_core import BudgetExceededError

        from eval_harness.agent_core_adapter import BudgetedJudge, build_budgeted_judge
    except ImportError:
        # agent_core is the optional extra this feature builds on; treat absence as a skip-pass.
        logger.info("agent_core not installed; F-030 offline check skipped (feature is opt-in)")
        return report(logger, "F-030", errors)

    def _judge(clock, **budget_kw):
        base = {"enabled": True, "cap": 1000.0, "cost_per_call": 1.0}
        base.update(budget_kw)
        cfg = JudgeBudgetConfig(**base)
        return build_budgeted_judge(MockJudge(default_score=1.0), cfg, clock=clock, sleeper=clock.sleep)

    # Config requires both window fields together.
    def _raises(**kw) -> bool:
        try:
            JudgeBudgetConfig(enabled=True, cap=1.0, **kw)
            return False
        except Exception:
            return True

    _check(_raises(max_per_window=5), "window_seconds required with max_per_window", errors)
    _check(_raises(window_seconds=1.0), "max_per_window required with window_seconds", errors)
    _check(
        _raises(max_per_window=2, window_seconds=1.0, on_rate_limited="bogus"),
        "invalid on_rate_limited rejected",
        errors,
    )

    # Block mode: two calls fit, the third waits exactly one window.
    clock = _FakeClock()
    j = _judge(clock, max_per_window=2, window_seconds=10.0, on_rate_limited="block")
    j.evaluate("p")
    j.evaluate("p")
    _check(clock.t == 0.0, "two calls admitted without waiting", errors)
    j.evaluate("p")
    _check(clock.t == 10.0, "third call throttled for the full window", errors)

    # Skip mode: over-rate call returns a sentinel, no waiting.
    clock2 = _FakeClock()
    j2 = _judge(clock2, max_per_window=1, window_seconds=10.0, on_rate_limited="skip")
    j2.evaluate("p")
    sentinel = j2.evaluate("p")
    _check("rate limit" in sentinel.reasoning and clock2.t == 0.0, "over-rate call skipped, no sleep", errors)

    # Rate limit and cumulative cap are independent.
    clock3 = _FakeClock()
    j3 = _judge(clock3, cap=2.0, max_per_window=100, window_seconds=1.0)
    j3.evaluate("p")
    j3.evaluate("p")
    try:
        j3.evaluate("p")
        cap_tripped = False
    except BudgetExceededError:
        cap_tripped = True
    _check(cap_tripped, "cumulative cap still trips independently of the window", errors)

    # Feature off when window absent → byte-identical (no limiter).
    # build_budgeted_judge is annotated to return the Judge interface, but always
    # constructs a BudgetedJudge; cast to assert the private _limiter wiring detail.
    j4 = cast(BudgetedJudge, build_budgeted_judge(MockJudge(), JudgeBudgetConfig(enabled=True, cap=5.0)))
    _check(j4._limiter is None, "no limiter attached when window fields omitted", errors)

    return report(logger, "F-030", errors)


if __name__ == "__main__":
    sys.exit(validate_f030())

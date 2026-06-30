#!/usr/bin/env python3
"""Validation script for F-022 - Judge Budget Cap.

Checks (skipped gracefully if agent_core is not installed):
    1. A BudgetedJudge admits calls under the cap and raises once it is exhausted.
    2. The ledger is built with reserve_fraction=0 so the usable budget == cap.
    3. on_exceeded='skip' returns a sentinel verdict instead of raising.
    4. EvalEngine.from_config leaves the judge unwrapped when budgeting is disabled.

Exit codes:
    0 - all checks passed (or skipped because agent_core is unavailable)
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    errors: list[str] = []

    try:
        import agent_core  # noqa: F401
    except ImportError:
        logger.warning("agent_core not installed - F-022 validation skipped (lazy-import contract).")
        return 0

    from agent_core import BudgetExceededError

    from eval_harness.agent_core_adapter import BudgetedJudge, build_budgeted_judge
    from eval_harness.config.models import ComponentSpec, EvalConfig, JudgeBudgetConfig, RunSettings
    from eval_harness.engine import EvalEngine
    from eval_harness.judges import MockJudge
    from eval_harness.plugins import bootstrap

    bootstrap()

    # 1. admit then exhaust
    budget = JudgeBudgetConfig(enabled=True, cap=2.0, cost_per_call=1.0)
    judge = build_budgeted_judge(MockJudge(default_score=0.6), budget)
    try:
        v1 = judge.evaluate("p")
        v2 = judge.evaluate("p")
        _check(v1.score == 0.6 and v2.score == 0.6, "two calls admitted under cap", errors)
        raised = False
        try:
            judge.evaluate("p")
        except BudgetExceededError:
            raised = True
        _check(raised, "third call raises BudgetExceededError (cap exhausted)", errors)
    except Exception as exc:
        errors.append(f"budgeted judge admission failed: {exc}")
        logger.error("budgeted judge admission failed: %s", exc)

    # 2. reserve_fraction=0 -> usable budget == cap (a cap of 3 admits exactly 3)
    judge3 = build_budgeted_judge(MockJudge(), JudgeBudgetConfig(enabled=True, cap=3.0, cost_per_call=1.0))
    admitted = 0
    for _ in range(5):
        try:
            judge3.evaluate("p")
            admitted += 1
        except BudgetExceededError:
            break
    _check(admitted == 3, f"usable budget equals cap (admitted {admitted}, expected 3)", errors)

    # 3. on_exceeded='skip'
    skipper = build_budgeted_judge(
        MockJudge(default_score=0.9), JudgeBudgetConfig(enabled=True, cap=1.0, cost_per_call=1.0, on_exceeded="skip")
    )
    skipper.evaluate("p")  # consumes the only unit
    sentinel = skipper.evaluate("p")
    _check(
        sentinel.score == 0.0 and "budget" in sentinel.reasoning, "on_exceeded='skip' returns sentinel verdict", errors
    )

    # 4. disabled -> engine judge is the bare judge (not wrapped)
    cfg = EvalConfig(
        schema_version="1.0",
        run=RunSettings(name="v"),
        dataset=ComponentSpec(type="inline", params={"items": [{"id": "a", "inputs": {}, "expected": "x"}]}),
        target=ComponentSpec(type="echo", params={}),
        scorers=[],
        judge=ComponentSpec(type="mock", params={}),
    )
    engine = EvalEngine.from_config(cfg)
    _check(not isinstance(engine.judge, BudgetedJudge), "judge unwrapped when budgeting disabled", errors)

    cfg_on = cfg.model_copy(update={"judge_budget": JudgeBudgetConfig(enabled=True, cap=5.0)})
    engine_on = EvalEngine.from_config(cfg_on)
    _check(isinstance(engine_on.judge, BudgetedJudge), "judge wrapped when budgeting enabled", errors)

    return report(logger, "F-022", errors)


if __name__ == "__main__":
    sys.exit(main())

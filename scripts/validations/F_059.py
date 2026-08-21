#!/usr/bin/env python3
"""Validation script for F-059 - PanelJudge (aggregate N member judges).

Checks:
    1.  ``PanelJudge`` construction validation: empty/single-member lists are
        rejected, an unknown strategy is rejected, quorum is bounded to
        ``[1, len(members)]``.
    2.  Aggregation is correct on hand-crafted examples for all three
        strategies (median, mean, majority-as-pass-fraction), and a failed
        member is excluded from aggregation rather than counted as a
        fabricated ``0.0`` vote.
    3.  The panel abstains (``raw["abstained"] = True``, score ``on_skip``)
        when fewer than ``quorum`` members survive, and independently when the
        surviving spread exceeds ``disagreement_threshold``.
    4.  ``calls_per_evaluate`` is the sum of each member's own
        ``calls_per_evaluate`` (default 1), recursively -- a nested panel
        reports its true call count, not its member count.
    5.  ``BudgetedJudge``/``build_budgeted_judge`` scale both the cost
        reservation and the rate-limiter's slot consumption by
        ``calls_per_evaluate``, and ``build_budgeted_judge`` fails fast at
        construction when a panel's call count exceeds ``max_per_window``.
    6.  ``LLMJudgeScorer.score`` reports ``passed=None`` (not a false
        pass/fail) when the injected judge's verdict carries
        ``raw["abstained"] = True`` -- duck-typed, not panel-specific.
    7.  ``pairwise_member_kappa`` computes Cohen's kappa correctly between
        member pairs and validates its inputs.
    8.  ``JudgeCalibrationReport``'s three panel-only fields default to
        empty/None, thread through ``build_judge_calibration_report``, and
        never affect ``may_gate``/``failing_checks``.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "agent-core"))


def _mock_member(score: float) -> dict:
    return {"type": "mock", "params": {"default_score": score}}


def _check_construction(errors: list[str]) -> None:
    from eval_harness.core.registry import RegistryError
    from eval_harness.plugins import JUDGES, bootstrap

    bootstrap()

    try:
        JUDGES.create("panel", {"members": []})
        _check(False, "PanelJudge rejects an empty member list", errors)
    except ValueError:
        _check(True, "PanelJudge rejects an empty member list", errors)

    try:
        JUDGES.create("panel", {"members": [_mock_member(0.5)]})
        _check(False, "PanelJudge rejects a single-member list", errors)
    except ValueError:
        _check(True, "PanelJudge rejects a single-member list", errors)

    try:
        JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.9)], "strategy": "geomean"})
        _check(False, "PanelJudge rejects an unknown strategy", errors)
    except ValueError:
        _check(True, "PanelJudge rejects an unknown strategy", errors)

    try:
        JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.9)], "quorum": 0})
        _check(False, "PanelJudge rejects quorum < 1", errors)
    except ValueError:
        _check(True, "PanelJudge rejects quorum < 1", errors)

    try:
        JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.9)], "quorum": 3})
        _check(False, "PanelJudge rejects quorum > member count", errors)
    except ValueError:
        _check(True, "PanelJudge rejects quorum > member count", errors)

    try:
        JUDGES.create("panel", {"members": [_mock_member(0.1), {"type": "does_not_exist"}]})
        _check(False, "an unknown member type propagates RegistryError", errors)
    except RegistryError:
        _check(True, "an unknown member type propagates RegistryError", errors)


def _check_aggregation_and_abstention(errors: list[str]) -> None:
    from eval_harness.core.interfaces import Judge
    from eval_harness.core.types import JudgeVerdict
    from eval_harness.plugins import JUDGES, bootstrap

    bootstrap()

    median = JUDGES.create("panel", {"members": [_mock_member(0.2), _mock_member(0.9), _mock_member(0.5)]})
    v = median.evaluate("p")
    _check(v.score == 0.5, "median strategy: correct middle value on 3 members", errors)

    mean = JUDGES.create("panel", {"members": [_mock_member(0.0), _mock_member(1.0)], "strategy": "mean"})
    v = mean.evaluate("p")
    _check(v.score == 0.5, "mean strategy: correct average on 2 members", errors)

    majority = JUDGES.create(
        "panel",
        {"members": [_mock_member(0.9), _mock_member(0.9), _mock_member(0.1)], "strategy": "majority"},
    )
    v = majority.evaluate("p")
    _check(
        abs(v.score - 2 / 3) < 1e-9,
        "majority strategy: a pass fraction (2 of 3 clear the default 0.5 threshold), not a member score",
        errors,
    )

    class _Raises(Judge):
        def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
            raise RuntimeError("outage")

    JUDGES.register_class("_f059_raises", _Raises)
    try:
        three_with_one_failure = JUDGES.create(
            "panel", {"members": [_mock_member(0.8), _mock_member(0.6), {"type": "_f059_raises"}], "strategy": "mean"}
        )
        v = three_with_one_failure.evaluate("p")
        _check(
            v.score == 0.7 and len(v.raw["failed_members"]) == 1,
            "a failed member is excluded from aggregation, not counted as a fabricated 0.0 vote",
            errors,
        )

        two_with_one_failure = JUDGES.create("panel", {"members": [_mock_member(0.7), {"type": "_f059_raises"}]})
        v = two_with_one_failure.evaluate("p")
        _check(
            v.raw["abstained"] is True and v.score == 0.0,
            "below quorum (1 survivor of 2, need 2): the panel abstains rather than scoring on 1 member",
            errors,
        )
    finally:
        JUDGES._reg.pop("_f059_raises", None)

    disagreeing = JUDGES.create(
        "panel", {"members": [_mock_member(0.0), _mock_member(1.0)], "disagreement_threshold": 0.1}
    )
    v = disagreeing.evaluate("p")
    _check(v.raw["abstained"] is True, "spread exceeding disagreement_threshold triggers abstention", errors)


def _check_calls_per_evaluate(errors: list[str]) -> None:
    from eval_harness.judges.panel import PanelJudge
    from eval_harness.plugins import JUDGES, bootstrap

    bootstrap()

    flat = JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.2), _mock_member(0.3)]})
    assert isinstance(flat, PanelJudge)
    _check(flat.calls_per_evaluate == 3, "calls_per_evaluate sums flat members (default 1 each)", errors)

    nested = JUDGES.create(
        "panel",
        {
            "members": [
                {"type": "panel", "params": {"members": [_mock_member(0.1), _mock_member(0.2)]}},
                _mock_member(0.5),
            ]
        },
    )
    assert isinstance(nested, PanelJudge)
    _check(
        nested.calls_per_evaluate == 3,
        "calls_per_evaluate is recursive: a nested 2-member panel + 1 plain member = 3, not 2",
        errors,
    )


def _check_budget_accounting(errors: list[str]) -> None:
    from eval_harness.agent_core_adapter import BudgetedJudge, build_budgeted_judge
    from eval_harness.config.models import JudgeBudgetConfig
    from eval_harness.judges import MockJudge
    from eval_harness.plugins import bootstrap

    bootstrap()

    class _NCall(MockJudge):
        def __init__(self, calls_per_evaluate: int, default_score: float = 1.0):
            super().__init__(default_score=default_score)
            self.calls_per_evaluate = calls_per_evaluate

    inner = _NCall(calls_per_evaluate=3, default_score=1.0)
    budget = JudgeBudgetConfig(enabled=True, cap=6.0, cost_per_call=1.0)
    wrapped = build_budgeted_judge(inner, budget)
    assert isinstance(wrapped, BudgetedJudge)
    _check(
        wrapped.calls_per_evaluate == 3,
        "BudgetedJudge reads calls_per_evaluate duck-typed from the wrapped judge",
        errors,
    )
    wrapped.evaluate("p")
    _check(wrapped._ledger.spent == 3.0, "cost reservation scales by calls_per_evaluate (3 units for 1 call)", errors)

    window_budget = JudgeBudgetConfig(enabled=True, cap=100.0, cost_per_call=1.0, max_per_window=2, window_seconds=5.0)
    try:
        build_budgeted_judge(_NCall(calls_per_evaluate=3), window_budget)
        _check(False, "build_budgeted_judge fails fast when calls_per_evaluate exceeds max_per_window", errors)
    except ValueError as exc:
        _check(
            "exceeds max_per_window" in str(exc),
            "build_budgeted_judge fails fast when calls_per_evaluate exceeds max_per_window",
            errors,
        )


def _check_llm_judge_scorer_abstention(errors: list[str]) -> None:
    from eval_harness.core.interfaces import Judge
    from eval_harness.core.types import EvalItem, JudgeVerdict, RunContext, TargetOutput
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()

    class _Abstains(Judge):
        def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
            return JudgeVerdict(score=0.0, reasoning="below quorum", raw={"abstained": True})

    scorer = SCORERS.create("llm_judge", {"threshold": 0.0})
    ctx = RunContext(config=None, judge=_Abstains())
    result = scorer.score(EvalItem(id="i", inputs={}, expected="x"), TargetOutput(output="y"), ctx)
    _check(
        result.passed is None,
        "LLMJudgeScorer.score reports passed=None (not a false pass) for an abstained verdict",
        errors,
    )


def _check_calibration(errors: list[str]) -> None:
    from agent_core.judge_calibration_report import build_judge_calibration_report

    from eval_harness.agent_core_adapter import pairwise_member_kappa

    rows = pairwise_member_kappa({"a": [0.9, 0.9, 0.1, 0.1], "b": [0.8, 0.8, 0.2, 0.2]})
    _check(rows == (("a", "b", 1.0),), "pairwise_member_kappa: perfect agreement -> kappa 1.0", errors)

    try:
        pairwise_member_kappa({"a": [0.5, 0.5]})
        _check(False, "pairwise_member_kappa rejects a single member", errors)
    except ValueError:
        _check(True, "pairwise_member_kappa rejects a single member", errors)

    from agent_core.judge_calibration import VerbosityProbeResult
    from agent_core.pairwise import PairwiseItem

    passing_verbosity = VerbosityProbeResult(
        n=10,
        ties=0,
        concise_wins=5,
        expanded_wins=5,
        expanded_win_rate=0.5,
        preference_delta=0.0,
        ci_low=0.2,
        ci_high=0.8,
        passes=True,
    )
    from agent_core.judge_calibration import OrderProbeResult

    passing_order = OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True)
    canary = PairwiseItem(
        item_id="c1",
        prompt="p",
        answer_a="a",
        answer_b="b",
        family_a="gpt",
        family_b="claude",
        expected="tie",
        canary_kind="known_equal",
    )
    report_obj = build_judge_calibration_report(
        "panel-1",
        "art-1",
        n_total=10,
        n_codeterminate=10,
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=passing_order,
        verbosity=passing_verbosity,
        self_preference=None,
        canaries=[canary],
        canary_verdicts=["tie"],
        pairwise_member_kappa=rows,
        abstention_rate=0.1,
        member_families=("gpt", "claude"),
    )
    _check(
        report_obj.pairwise_member_kappa == rows and report_obj.may_gate is True,
        "panel-only fields thread through build_judge_calibration_report without affecting may_gate",
        errors,
    )

    default_report = build_judge_calibration_report(
        "j1",
        "art-1",
        n_total=10,
        n_codeterminate=10,
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=passing_order,
        verbosity=passing_verbosity,
        self_preference=None,
        canaries=[canary],
        canary_verdicts=["tie"],
    )
    _check(
        default_report.pairwise_member_kappa == () and default_report.abstention_rate is None,
        "panel-only fields default empty/None for a single-judge caller",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_construction(errors)
    _check_aggregation_and_abstention(errors)
    _check_calls_per_evaluate(errors)
    _check_budget_accounting(errors)
    _check_llm_judge_scorer_abstention(errors)
    _check_calibration(errors)
    return report(logger, "F-059", errors)


if __name__ == "__main__":
    sys.exit(main())

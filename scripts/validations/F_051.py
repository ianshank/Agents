#!/usr/bin/env python3
"""Validation script for F-051 - Agent trajectory evaluation.

Checks:
    1.  All seven trajectory scorers are registered, each with a hyphenated alias.
    2.  ``TargetOutput`` keeps its historical positional signature and stays mutable,
        with ``trajectory`` appended last (ADR 0031 obligations 1-2).
    3.  A trajectory-free run serialises with no ``trajectory`` key at all, so
        pre-F-051 result JSON is byte-identical (ADR 0031 obligation 4).
    4.  Exact matching fails and in-order matching passes on the same A,X,B candidate.
    5.  Any-order matching ignores order and behaves as a multiset, not a set.
    6.  Precision and recall are reported separately for a duplicate-and-omission case.
    7.  Step efficiency reports excess work against a budget.
    8.  Recovery fails a false success after a tool error, and passes a retry.
    9.  A missing trajectory yields ``passed=None`` (not a failing 0.0), and is
        therefore excluded from the aggregate pass rate.
    10. Normalisation canonicalises names and nested argument ordering, drops
        configured volatile fields at any depth, and preserves duplicate calls.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_SCORER_NAMES = (
    "trajectory_exact",
    "trajectory_in_order",
    "trajectory_any_order",
    "trajectory_precision_recall",
    "trajectory_step_efficiency",
    "trajectory_loop_detection",
    "trajectory_recovery",
)


def main() -> int:
    configure_logging()
    errors: list[str] = []

    from eval_harness.core._trajectory import NormalizationConfig, canonical_call, canonical_calls
    from eval_harness.core.types import (
        AgentTrajectory,
        EvalItem,
        ItemResult,
        RunContext,
        RunResult,
        ScoreResult,
        TargetOutput,
        ToolCallRecord,
        TrajectoryStep,
    )
    from eval_harness.engine import EvalEngine
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()
    ctx = RunContext(config=None)

    def call(name: str, **arguments: object) -> TrajectoryStep:
        return TrajectoryStep(kind="tool_call", tool_call=ToolCallRecord(name=name, arguments=arguments))

    def traj(*steps: TrajectoryStep) -> AgentTrajectory:
        return AgentTrajectory(steps=tuple(steps))

    def out(*steps: TrajectoryStep) -> TargetOutput:
        return TargetOutput(output="answer", trajectory=traj(*steps))

    def item(expected: object = None, **metadata: object) -> EvalItem:
        return EvalItem(id="i", inputs={}, expected=expected, metadata=metadata)

    def score(name: str, target_output: TargetOutput, expected: object = None, **params: object) -> ScoreResult:
        return SCORERS.create(name, params).score(item(expected), target_output, ctx)

    # 1. registration + aliases
    for name in _SCORER_NAMES:
        _check(name in SCORERS, f"{name} registered", errors)
        alias = name.replace("_", "-")
        _check(SCORERS.resolve(alias) == name, f"alias '{alias}' resolves to '{name}'", errors)

    # 2. ADR 0031 obligations 1-2: appended field, still mutable, order unchanged
    legacy = TargetOutput("text", 12.5, "boom", {"k": "v"})
    _check(
        (legacy.output, legacy.latency_ms, legacy.error, legacy.metadata) == ("text", 12.5, "boom", {"k": "v"}),
        "historical positional TargetOutput(output, latency_ms, error, metadata) still works",
        errors,
    )
    _check(legacy.trajectory is None, "trajectory defaults to None", errors)
    legacy.output = "mutated"
    _check(legacy.output == "mutated", "TargetOutput is still mutable (not frozen)", errors)

    # 3. ADR 0031 obligation 4: no trajectory key when no trajectory
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def run_of(target_output: TargetOutput) -> RunResult:
        return RunResult(
            run_id="r",
            config_name="c",
            items=[ItemResult(item=item(), output=target_output)],
            aggregate={},
            started_at=moment,
            finished_at=moment,
        )

    plain = run_of(TargetOutput(output="plain")).to_dict()["items"][0]
    _check("trajectory" not in plain, "trajectory-free item serialises with no trajectory key", errors)
    _check(
        set(plain) == {"id", "inputs", "expected", "output", "error", "latency_ms", "scores"},
        "trajectory-free item payload keys are unchanged from pre-F-051",
        errors,
    )
    with_traj = run_of(out(call("search", q="x"))).to_dict()["items"][0]
    _check("trajectory" in with_traj, "trajectory is serialised when present", errors)
    _check(
        with_traj["trajectory"]["steps"][0]["tool_call"] == {"name": "search", "arguments": {"q": "x"}},
        "serialised tool call carries name and arguments",
        errors,
    )

    # 4. exact vs in-order on the same candidate
    axb = out(call("A"), call("X"), call("B"))
    _check(score("trajectory_exact", axb, ["A", "B"]).passed is False, "exact rejects an extra call", errors)
    _check(score("trajectory_in_order", axb, ["A", "B"]).passed is True, "in-order tolerates an extra call", errors)

    # 5. any-order: ignores order, multiset not set
    _check(
        score("trajectory_any_order", out(call("B"), call("A")), ["A", "B"]).passed is True,
        "any-order ignores call order",
        errors,
    )
    _check(
        score("trajectory_any_order", out(call("A")), ["A", "A"]).passed is False,
        "any-order is a multiset: one call does not satisfy a reference asking for two",
        errors,
    )

    # 6. precision and recall reported separately
    pr = score("trajectory_precision_recall", out(call("A"), call("A")), ["A", "B"])
    _check(
        abs(pr.metadata["precision"] - 0.5) < 1e-9 and abs(pr.metadata["recall"] - 0.5) < 1e-9,
        f"duplicate+omission reports precision and recall separately (got {pr.metadata})",
        errors,
    )

    # 7. step efficiency surfaces excess work
    wasteful = out(*[call(f"t{n}") for n in range(14)])
    eff = score("trajectory_step_efficiency", wasteful, budget=4)
    _check(eff.passed is False, "fourteen steps against a four-step budget fails step efficiency", errors)
    _check(eff.metadata["actual"] == 14 and eff.metadata["budget"] == 4, "step efficiency reports the excess", errors)

    # 8. recovery
    error_step = TrajectoryStep(kind="tool_error", tool_call=ToolCallRecord("a"))
    false_success = out(call("a"), error_step, TrajectoryStep(kind="final", content="all done"))
    _check(
        score("trajectory_recovery", false_success).passed is False,
        "claiming success after an unrecovered tool error fails recovery",
        errors,
    )
    retried = out(call("a"), error_step, call("a"), TrajectoryStep(kind="final", content="done"))
    _check(score("trajectory_recovery", retried).passed is True, "a retry after a tool error passes recovery", errors)

    # 9. the not-applicable path, and its effect on the aggregate
    text_only = TargetOutput(output="just text")
    for name in _SCORER_NAMES:
        result = score(name, text_only, ["A"])
        _check(result.passed is None, f"{name} reports not-applicable (not a failure) with no trajectory", errors)
    aggregate = EvalEngine._aggregate(
        [
            ItemResult(item=item(), output=text_only, scores=[ScoreResult("s", value=0.0, passed=None)]),
            ItemResult(item=item(), output=text_only, scores=[ScoreResult("s", value=1.0, passed=True)]),
        ]
    )["s"]
    _check(aggregate.pass_rate == 1.0, "a None verdict is excluded from the aggregate pass rate", errors)

    # 10. normalisation
    cfg = NormalizationConfig(ignore_fields=frozenset({"req_id"}))
    left = ToolCallRecord("Search", {"q": "x", "req_id": "1", "nested": {"req_id": "a", "keep": 1}})
    right = ToolCallRecord("search", {"nested": {"keep": 1, "req_id": "b"}, "req_id": "2", "q": "x"})
    _check(
        canonical_call(left, cfg) == canonical_call(right, cfg),
        "normalisation canonicalises names and nested key order and drops ignored fields at depth",
        errors,
    )
    duplicates = canonical_calls([ToolCallRecord("a"), ToolCallRecord("a")], NormalizationConfig())
    _check(len(duplicates) == 2, "normalisation preserves duplicate calls", errors)

    return report(logger, "F-051", errors)


if __name__ == "__main__":
    sys.exit(main())

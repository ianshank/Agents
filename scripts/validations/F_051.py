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
    11. Canonicalisation is stable ACROSS interpreter processes (sets sorted by value,
        unknown types rendered as type:value, never a memory address).
    12. Value-object mappings are read-only, so a record cannot change its own canonical form.
    13. Unscoreable input reports not-applicable, never a failing verdict.
    14. trajectory_recovery is linear and emits a stable metadata key set on both branches.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime

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

    def final_step() -> TrajectoryStep:
        return TrajectoryStep(kind="final")

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
    moment = datetime(2026, 1, 1, tzinfo=UTC)

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

    # 11. cross-process determinism -- the assertion has to spawn real subprocesses:
    # set iteration order and str(object()) are stable WITHIN a process, so a
    # same-process check passes against the very bug it is meant to catch.
    src_dir = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
    probe = (
        f"import sys; sys.path.insert(0, {src_dir!r})\n"
        "from eval_harness.core._trajectory import NormalizationConfig, canonical_call\n"
        "from eval_harness.core.types import ToolCallRecord\n"
        "print(canonical_call(ToolCallRecord('t', {'s': {'a','b','c'}, 'o': object()}), NormalizationConfig())[1])\n"
    )
    forms = set()
    for seed in ("0", "1", "2", "3"):
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=False,
            timeout=30,
        )
        forms.add(proc.stdout.strip())
    _check(len(forms) == 1, f"canonical form is identical under every PYTHONHASHSEED (got {len(forms)})", errors)
    _check(all("0x" not in form for form in forms), "no canonical form contains a memory address", errors)

    # 12. read-only value-object mappings
    record = ToolCallRecord("t", {"a": 1})
    for label, mapping in (
        ("ToolCallRecord.arguments", record.arguments),
        ("TrajectoryStep.metadata", final_step().metadata),
    ):
        try:
            mapping["x"] = 1  # type: ignore[index]
            _check(False, f"{label} is read-only", errors)
        except TypeError:
            _check(True, f"{label} is read-only", errors)

    # 13. unscoreable input is not-applicable, never a failing verdict
    deep: dict = {}
    cursor = deep
    for _ in range(10):
        cursor["n"] = {}
        cursor = cursor["n"]
    _check(
        score("trajectory_exact", out(call("t", **deep)), ["t"], max_depth=3).passed is None,
        "arguments nested past max_depth report not-applicable, not a failure",
        errors,
    )
    _check(
        score("trajectory_exact", out(call("t")), [{"name": "t", "arguments": None}]).passed is None,
        "a reference call with non-mapping arguments reports not-applicable, not a failure",
        errors,
    )

    # 14. recovery is linear and its metadata shape is stable
    error_steps = tuple(TrajectoryStep(kind="tool_error", tool_call=ToolCallRecord(f"t{n}")) for n in range(5000))
    many_errors = out(*error_steps, TrajectoryStep(kind="final"))
    started = time.perf_counter()
    recovery = score("trajectory_recovery", many_errors)
    elapsed = time.perf_counter() - started
    _check(elapsed < 2.0, f"5000-error trajectory scores in under 2s (took {elapsed:.3f}s)", errors)
    clean_recovery = score("trajectory_recovery", out(TrajectoryStep(kind="final")))
    _check(
        set(recovery.metadata) == set(clean_recovery.metadata) == {"tool_errors", "unrecovered_tools"},
        "recovery emits the same metadata keys on the pass and fail branches",
        errors,
    )

    return report(logger, "F-051", errors)


if __name__ == "__main__":
    sys.exit(main())

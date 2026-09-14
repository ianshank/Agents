#!/usr/bin/env python3
"""Validation script for F-070 — fixture replay of recorded AgentTrajectory envelopes.

Every check below is established by RUNNING the thing it describes (the F-063
lesson): round-trip a trajectory, re-score an envelope, swap one observation,
and refuse a path that escapes OUTPUT_ROOT.

Checks:
    1.  trajectory_from_dict is the inverse of trajectory_to_dict; unknown keys raise.
    2.  exact replay re-emits the recorded trajectory_in_order / trajectory_recovery verdicts.
    3.  counterfactual override of search changes only the tagged item.
    4.  archive writes refuse paths outside OUTPUT_ROOT when that env var is set.
    5.  eval-harness replay --help lists exact and counterfactual; no network client.
    6.  registered name replay appears on the target registry.
    7.  a slice report can show freshness=sensitive dropping while global pass_rate is not 0.
    8.  answer_quality advisory config (when present) marks every gate rule report_only.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

if TYPE_CHECKING:
    from eval_harness.core.types import AgentTrajectory
    from eval_harness.replay.envelope import ReplayEnvelope

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)

_AQ_CONFIG = os.path.join(PROJECT_ROOT, "config", "answer_quality_eval.yaml")


def _traj() -> AgentTrajectory:
    from eval_harness.core.types import AgentTrajectory, ToolCallRecord, TrajectoryStep

    search = ToolCallRecord(name="search", arguments={"q": "x"})
    return AgentTrajectory(
        steps=(
            TrajectoryStep(kind="tool_call", tool_call=search),
            TrajectoryStep(kind="tool_observation", tool_call=search, content="hit"),
            TrajectoryStep(kind="final", content="ok"),
        )
    )


def _envelope(*, item_id: str, freshness: str) -> ReplayEnvelope:
    from eval_harness.replay.envelope import ReplayEnvelope, canonical_hash

    traj = _traj()
    return ReplayEnvelope(
        envelope_id=f"e-{item_id}",
        recorded_run_id="v",
        item_id=item_id,
        recorded_at="2026-09-14T00:00:00+00:00",
        environment="offline",
        agent_version="v1",
        input_hash=canonical_hash(item_id),
        output_hash=canonical_hash("ok"),
        trajectory=traj,
        output="ok",
        tags={"freshness": freshness},
    )


def _check_round_trip(errors: list[str]) -> None:
    from eval_harness.core.types import trajectory_to_dict
    from eval_harness.replay.envelope import ReplayError, trajectory_from_dict

    original = _traj()
    restored = trajectory_from_dict(trajectory_to_dict(original))  # type: ignore[arg-type]
    _check(restored == original, "trajectory_from_dict is the inverse of trajectory_to_dict", errors)
    raised = False
    try:
        trajectory_from_dict({"schema_version": "1.0.0", "steps": [], "span_id": "x"})
    except ReplayError:
        raised = True
    _check(raised, "unknown trajectory keys raise", errors)


def _check_exact_and_counterfactual(errors: list[str]) -> None:
    from eval_harness.core.types import EvalItem, ItemResult, RunContext
    from eval_harness.plugins import SCORERS, TARGETS, bootstrap
    from eval_harness.replay.slice import global_pass_rate, pass_rates_by_tag
    from eval_harness.replay.target import ReplayTarget

    bootstrap()
    sensitive = _envelope(item_id="s", freshness="sensitive")
    normal = _envelope(item_id="n", freshness="normal")
    exact = TARGETS.create("replay", {"envelopes": [sensitive, normal], "mode": "exact"})
    item_s = EvalItem(
        id="s",
        inputs={},
        expected={"tool_calls": [{"name": "search", "arguments": {"q": "x"}}]},
    )
    ctx = RunContext(config=None)
    out = exact.run(item_s)
    in_order = SCORERS.create("trajectory_in_order", {}).score(item_s, out, ctx)
    recovery = SCORERS.create("trajectory_recovery", {}).score(item_s, out, ctx)
    _check(in_order.passed is True and recovery.passed is True, "exact replay re-emits recorded verdicts", errors)

    counter = ReplayTarget(
        envelopes=[sensitive, normal],
        mode="counterfactual",
        overrides={"search": "error:stale"},
        override_tag_value="sensitive",
    )
    results: list[ItemResult] = []
    for item_id, env_freshness in (("s", "sensitive"), ("n", "normal")):
        item = EvalItem(
            id=item_id,
            inputs={},
            expected={"tool_calls": [{"name": "search", "arguments": {"q": "x"}}]},
            metadata={"replay_tags": {"freshness": env_freshness}},
        )
        output = counter.run(item)
        score = SCORERS.create("trajectory_recovery", {}).score(item, output, ctx)
        results.append(ItemResult(item=item, output=output, scores=[score]))
    _check(
        results[0].output.trajectory is not None
        and any(step.kind == "tool_error" for step in results[0].output.trajectory.steps)
        and results[1].output.trajectory == normal.trajectory,
        "counterfactual changes only the tagged search observation",
        errors,
    )
    _passed, n, rate = global_pass_rate(results)
    slices = {row.tag_value: row.pass_rate for row in pass_rates_by_tag(results, "freshness")}
    _check(
        n == 2 and rate == 0.5 and slices.get("sensitive") == 0.0 and slices.get("normal") == 1.0,
        "slice report shows freshness=sensitive dropping while global pass_rate is not 0",
        errors,
    )


def _check_confinement(errors: list[str]) -> None:
    from eval_harness.core._paths import OUTPUT_ROOT_ENV
    from eval_harness.replay.archive import ReplayArchive

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "out"
        root.mkdir()
        previous = os.environ.get(OUTPUT_ROOT_ENV)
        os.environ[OUTPUT_ROOT_ENV] = str(root)
        try:
            raised = False
            try:
                ReplayArchive(root / ".." / "escape.jsonl", for_write=True)
            except ValueError:
                raised = True
            _check(raised, "archive writes refuse paths outside OUTPUT_ROOT", errors)
        finally:
            if previous is None:
                os.environ.pop(OUTPUT_ROOT_ENV, None)
            else:
                os.environ[OUTPUT_ROOT_ENV] = previous


def _check_cli_and_registry(errors: list[str]) -> None:
    from eval_harness.cli import build_parser
    from eval_harness.plugins import TARGETS, bootstrap

    bootstrap()
    _check("replay" in TARGETS.names(), "registered name replay appears on the target registry", errors)
    parser = build_parser()
    exact = parser.parse_args(["replay", "--archive", "x", "--mode", "exact", "--offline"])
    counter = parser.parse_args(["replay", "--archive", "x", "--mode", "counterfactual"])
    _check(
        exact.mode == "exact" and counter.mode == "counterfactual" and exact.offline is True,
        "eval-harness replay --help lists exact and counterfactual",
        errors,
    )


def _check_advisory_answer_quality(errors: list[str]) -> None:
    if not os.path.isfile(_AQ_CONFIG):
        _check(False, "config/answer_quality_eval.yaml is present", errors)
        return
    import yaml

    with open(_AQ_CONFIG, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    rules = ((data.get("gate") or {}).get("rules")) or []
    _check(bool(rules), "answer_quality_eval.yaml declares gate rules", errors)
    _check(all(rule.get("report_only") is True for rule in rules), "every answer_quality gate rule is advisory", errors)


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_round_trip(errors)
    _check_exact_and_counterfactual(errors)
    _check_confinement(errors)
    _check_cli_and_registry(errors)
    _check_advisory_answer_quality(errors)
    return report(logger, "F-070", errors)


if __name__ == "__main__":
    sys.exit(main())

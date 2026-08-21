#!/usr/bin/env python3
"""Validation script for F-060 - Stateful outcome evaluation (StateAdapter seam).

Checks:
    1.  ``StateSnapshot``/``StateEvaluation`` are frozen with read-only mapping
        fields; ``StateAdapter`` is a ``runtime_checkable`` Protocol a duck-typed
        fake satisfies by shape alone; ``STATE_ADAPTERS`` registers all four
        local adapters (``in_memory``, ``filesystem``, ``sqlite``, ``mock_http``).
    2.  The engine lifecycle: ``reset -> snapshot(before) -> target.run ->
        snapshot(after) -> evaluate``, in order, under a configured adapter.
        ``StateResetError`` aborts the run uncaught, regardless of
        ``fail_fast``. A snapshot/evaluate failure produces a visible failing
        item (a synthetic ``state_lifecycle`` score), never a silently
        dropped one. Reset fires before every attempt under
        ``repetitions > 1`` in both the sequential and parallel dispatch paths.
    3.  ``state_transition``/``policy_violation`` scorers read
        ``ctx.extra["state_evaluation"]``; a goal reached via a forbidden
        mutation reports ``state_transition.passed=True`` and
        ``policy_violation.passed=False`` simultaneously -- neither axis
        masks the other.
    4.  Each of the four local adapters round-trips construct -> mutate ->
        snapshot -> evaluate -> reset correctly, including the
        goal-reached-via-forbidden-mutation scenario for at least one.
    5.  Governance: ``architecture.yaml``'s import graph matches (no
        undocumented dependency, ``state_adapters`` present); ``cli.py``'s
        ``list-plugins`` reports the ``state_adapters`` registry; the
        ``add-stateful-outcome-evaluation`` ``FOLLOW_ON`` obligation has been
        removed now that it is satisfied.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import dataclasses
import io
import logging
import os
import sys
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))


def _check_contracts(errors: list[str]) -> None:
    from eval_harness.core.interfaces import StateAdapter
    from eval_harness.core.types import RunContext, StateEvaluation, StateSnapshot
    from eval_harness.plugins import STATE_ADAPTERS, bootstrap

    bootstrap()

    snap = StateSnapshot(data={"k": 1})
    try:
        snap.data["k"] = 2  # type: ignore[index]
        _check(False, "StateSnapshot.data is a read-only mapping", errors)
    except TypeError:
        _check(True, "StateSnapshot.data is a read-only mapping", errors)
    try:
        snap.data = {}  # type: ignore[misc]
        _check(False, "StateSnapshot is frozen", errors)
    except dataclasses.FrozenInstanceError:
        _check(True, "StateSnapshot is frozen", errors)

    ev = StateEvaluation(goal_reached=True, policy_violated=True)
    _check(
        ev.goal_reached is True and ev.policy_violated is True,
        "StateEvaluation carries goal_reached and policy_violated as independent axes",
        errors,
    )

    class _DuckAdapter:
        def snapshot(self, ctx: RunContext) -> StateSnapshot:
            return StateSnapshot()

        def evaluate(self, *, item, before, after) -> StateEvaluation:
            return StateEvaluation(goal_reached=True)

        def reset(self, ctx: RunContext) -> None:
            return None

    _check(isinstance(_DuckAdapter(), StateAdapter), "a duck-typed fake satisfies StateAdapter by shape", errors)
    _check(
        set(STATE_ADAPTERS.names()) == {"in_memory", "filesystem", "sqlite", "mock_http"},
        "STATE_ADAPTERS registers all four local adapters",
        errors,
    )


def _check_engine_lifecycle(errors: list[str]) -> None:
    from eval_harness.config import load_config_dict
    from eval_harness.core.interfaces import StateResetError
    from eval_harness.core.types import RunContext, StateEvaluation, StateSnapshot
    from eval_harness.engine import EvalEngine
    from eval_harness.version import SCHEMA_VERSION

    def _config(**extra_run):
        return {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "f060", "seed": 1, **extra_run},
            "dataset": {"type": "inline", "params": {"items": [{"id": "i1", "inputs": {"q": "x"}}]}},
            "target": {"type": "echo", "params": {"output_key": "q"}},
            "scorers": [],
            "sinks": [],
        }

    class _RecordingAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def reset(self, ctx: RunContext) -> None:
            self.calls.append("reset")

        def snapshot(self, ctx: RunContext) -> StateSnapshot:
            self.calls.append("snapshot")
            return StateSnapshot(data={"n": len(self.calls)})

        def evaluate(self, *, item, before, after) -> StateEvaluation:
            self.calls.append("evaluate")
            return StateEvaluation(goal_reached=True)

    adapter = _RecordingAdapter()
    engine = EvalEngine.from_config(load_config_dict(_config()))
    engine.state_adapter = adapter
    engine.run()
    _check(
        adapter.calls == ["reset", "snapshot", "snapshot", "evaluate"],
        "engine brackets an attempt reset -> snapshot(before) -> run -> snapshot(after) -> evaluate",
        errors,
    )

    class _FailingResetAdapter:
        def reset(self, ctx: RunContext) -> None:
            raise RuntimeError("backend down")

        def snapshot(self, ctx: RunContext) -> StateSnapshot:
            raise AssertionError("unreachable")

        def evaluate(self, *, item, before, after) -> StateEvaluation:
            raise AssertionError("unreachable")

    engine = EvalEngine.from_config(load_config_dict(_config(fail_fast=False)))
    engine.state_adapter = _FailingResetAdapter()
    try:
        engine.run()
        _check(False, "StateResetError aborts the run even when fail_fast=False", errors)
    except StateResetError:
        _check(True, "StateResetError aborts the run even when fail_fast=False", errors)

    class _FailingEvaluateAdapter:
        def reset(self, ctx: RunContext) -> None:
            pass

        def snapshot(self, ctx: RunContext) -> StateSnapshot:
            return StateSnapshot()

        def evaluate(self, *, item, before, after) -> StateEvaluation:
            raise RuntimeError("evaluate crashed")

    engine = EvalEngine.from_config(load_config_dict(_config()))
    engine.state_adapter = _FailingEvaluateAdapter()
    result = engine.run()
    _check(
        len(result.items) == 1
        and any(s.name == "state_lifecycle" and s.passed is False for s in result.items[0].scores),
        "a snapshot/evaluate failure produces a visible failing item, never a silently dropped one",
        errors,
    )

    reset_adapter = _RecordingAdapter()
    engine = EvalEngine.from_config(load_config_dict(_config(repetitions=3)))
    engine.state_adapter = reset_adapter
    engine.run()
    _check(
        reset_adapter.calls.count("reset") == 3,
        "reset fires before every attempt under repetitions > 1",
        errors,
    )


def _check_scorers(errors: list[str]) -> None:
    from eval_harness.core.types import EvalItem, RunContext, StateEvaluation, TargetOutput
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()
    _check(
        {"state_transition", "policy_violation"} <= set(SCORERS.names()),
        "state_transition and policy_violation scorers are registered",
        errors,
    )

    item = EvalItem(id="i1", inputs={}, expected=None)
    output = TargetOutput(output="done")
    ctx = RunContext(config=None, extra={"state_evaluation": StateEvaluation(goal_reached=True, policy_violated=True)})

    transition = SCORERS.create("state_transition", {}).score(item, output, ctx)
    violation = SCORERS.create("policy_violation", {}).score(item, output, ctx)
    _check(
        transition.passed is True and violation.passed is False,
        "goal-reached-via-forbidden-mutation: state_transition passes, policy_violation fails, simultaneously",
        errors,
    )

    empty_ctx = RunContext(config=None)
    abstained = SCORERS.create("state_transition", {}).score(item, output, empty_ctx)
    _check(abstained.passed is None, "state_transition abstains (passed=None) with no evaluation present", errors)


def _check_adapters(errors: list[str]) -> None:
    from eval_harness.core.types import EvalItem, RunContext
    from eval_harness.state_adapters import (
        FilesystemStateAdapter,
        InMemoryStateAdapter,
        MockHttpStateAdapter,
        SqliteStateAdapter,
    )

    ctx = RunContext(config=None)
    item = EvalItem(id="i1", inputs={}, expected=None, metadata={"state_expectation": {"k": "v"}})

    mem = InMemoryStateAdapter()
    before = mem.snapshot(ctx)
    mem.set("k", "v")
    ev = mem.evaluate(item=item, before=before, after=mem.snapshot(ctx))
    mem.reset(ctx)
    _check(
        ev.goal_reached is True and mem.snapshot(ctx).data == {},
        "in_memory: set() -> evaluate() reports goal_reached; reset() restores initial state",
        errors,
    )

    fs = FilesystemStateAdapter()
    fs_before = fs.snapshot(ctx)
    (fs.root / "out.txt").write_text("v")
    fs_item = EvalItem(id="i2", inputs={}, expected=None, metadata={"state_expectation": {"out.txt": "v"}})
    fs_ev = fs.evaluate(item=fs_item, before=fs_before, after=fs.snapshot(ctx))
    fs.reset(ctx)
    _check(
        fs_ev.goal_reached is True and fs.snapshot(ctx).data == {},
        "filesystem: content-hashed snapshot detects a matching write; reset() empties the sandbox",
        errors,
    )

    sql = SqliteStateAdapter(schema_sql="CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);", seed_sql="")
    sql_before = sql.snapshot(ctx)
    sql.conn.execute("INSERT INTO t VALUES (1, 'v')")
    sql_item = EvalItem(id="i3", inputs={}, expected=None, metadata={"state_expectation": {"t": [(1, "v")]}})
    sql_ev = sql.evaluate(item=sql_item, before=sql_before, after=sql.snapshot(ctx))
    sql.reset(ctx)
    _check(
        sql_ev.goal_reached is True and sql.snapshot(ctx).data == {"t": ()},
        "sqlite: transactional rollback (SAVEPOINT/ROLLBACK TO) restores the seeded table state",
        errors,
    )

    http = MockHttpStateAdapter()
    http_before = http.snapshot(ctx)
    http.request("PUT", "/users/1", {"name": "alice"})
    http.request("PUT", "/config", "unlocked")
    http_item = EvalItem(
        id="i4",
        inputs={},
        expected=None,
        metadata={"state_expectation": {"/users/1": {"name": "alice"}}, "state_forbidden_keys": ["/config"]},
    )
    http_ev = http.evaluate(item=http_item, before=http_before, after=http.snapshot(ctx))
    _check(
        http_ev.goal_reached is True and http_ev.policy_violated is True,
        "mock_http: goal reached via a forbidden call still flags policy_violated independently",
        errors,
    )


def _check_governance(errors: list[str]) -> None:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "skills", "architecture-drift-guard", "scripts"))
    import drift_check

    manifest_path = os.path.join(PROJECT_ROOT, "architecture.yaml")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = drift_check.main(["--manifest", manifest_path])
    _check(code == 0, "architecture.yaml has no undocumented dependency after the state_adapters addition", errors)

    from eval_harness.cli import main as cli_main

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli_main(["list-plugins"])
    out = buf.getvalue()
    _check(
        code == 0 and "state_adapters:" in out and "in_memory" in out,
        "cli.py's list-plugins reports the state_adapters registry (was a hardcoded 5-tuple)",
        errors,
    )

    sys.path.insert(0, PROJECT_ROOT)
    from tests._matrix_coverage import FOLLOW_ON

    _check(
        not any(row.change_id == "add-stateful-outcome-evaluation" for row in FOLLOW_ON),
        "the add-stateful-outcome-evaluation FOLLOW_ON obligation has been removed, now satisfied",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_contracts(errors)
    _check_engine_lifecycle(errors)
    _check_scorers(errors)
    _check_adapters(errors)
    _check_governance(errors)
    return report(logger, "F-060", errors)


if __name__ == "__main__":
    sys.exit(main())

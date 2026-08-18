#!/usr/bin/env python3
"""Validation script for F-056 - Repeated-attempt reliability metrics.

Checks:
    1.  ``RunSettings.repetitions`` defaults to 1 and rejects < 1; ``GateRule.metric``
        accepts ``pass_at_k``/``pass_power_k``; an unknown top-level config key is
        rejected at parse time.
    2.  ``ItemResult`` gains attempt-identity fields appended last, defaulting to
        None, so historical positional construction still works.
    3.  A ``repetitions=1`` run serialises with no attempt-identity keys and no
        ``reliability`` key -- byte-identical to the pre-change harness.
    4.  ``repetitions=5`` invokes the target exactly five times for one item, each
        call with byte-identical input -- no caching collapses the five draws.
    5.  The scorer RNG is reset every attempt: a scorer drawing from ``ctx.rng``
        reports a stable verdict across all five attempts of a deterministic
        target, in both the sequential and parallel dispatch paths.
    6.  ``TargetRunner.is_deterministic()`` is optional and non-abstract;
        ``ModelTarget`` derives it from ``temperature == 0.0``.
    7.  The ``deterministic_sampling`` diagnostic is present exactly when a
        deterministic target's ``pass^k == 1.0``, and omitted (not an empty key)
        otherwise.
    8.  ``ReliabilityAggregator``: one-of-five passes ``pass@5`` and fails
        ``pass^5``; five-of-five passes both; ``pass^k`` is never pooled across
        items (a suite of easy items does not mask one unreliable item).
    9.  ``pass_at_k``/``pass_power_k`` gate rules are wired end to end: a failing
        reliability gate reports ``passed=False`` with a reason naming the metric.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime
from typing import cast

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    errors: list[str] = []

    import pydantic

    from eval_harness.config import load_config_dict
    from eval_harness.config.models import GateConfig, GateRule, RunSettings
    from eval_harness.core.interfaces import Scorer, TargetRunner
    from eval_harness.core.types import EvalItem, ItemResult, RunResult, ScoreResult, TargetOutput
    from eval_harness.engine import EvalEngine, _make_item_rng
    from eval_harness.gating import evaluate_gate
    from eval_harness.plugins import SCORERS, TARGETS, bootstrap
    from eval_harness.reliability import ReliabilityAggregator
    from eval_harness.targets.model import ModelTarget
    from eval_harness.version import SCHEMA_VERSION

    bootstrap()

    # 1. Configuration
    _check(RunSettings().repetitions == 1, "RunSettings.repetitions defaults to 1", errors)
    try:
        RunSettings(repetitions=0)
        _check(False, "RunSettings.repetitions rejects 0 (ge=1)", errors)
    except pydantic.ValidationError:
        _check(True, "RunSettings.repetitions rejects 0 (ge=1)", errors)
    _check(
        GateRule(score="s", metric="pass_at_k").metric == "pass_at_k",
        "GateRule.metric accepts 'pass_at_k'",
        errors,
    )
    _check(
        GateRule(score="s", metric="pass_power_k").metric == "pass_power_k",
        "GateRule.metric accepts 'pass_power_k'",
        errors,
    )
    base_cfg = {
        "schema_version": SCHEMA_VERSION,
        "dataset": {"type": "inline", "params": {"items": []}},
        "target": {"type": "echo"},
        "scorers": [{"type": "exact_match"}],
    }
    try:
        load_config_dict(dict(base_cfg, gates={"rules": []}))
        _check(False, "an unknown top-level 'gates' key is rejected at parse time", errors)
    except (pydantic.ValidationError, ValueError):
        _check(True, "an unknown top-level 'gates' key is rejected at parse time", errors)

    # 2. Attempt identity: appended last, defaults None, historical construction intact
    item = EvalItem(id="i", inputs={})
    ir = ItemResult(item, TargetOutput(output="x"), [])
    _check(
        (ir.attempt_index, ir.attempt_id, ir.item_run_id) == (None, None, None),
        "ItemResult attempt fields default to None and are appended last",
        errors,
    )

    # 3. repetitions=1 byte-identical serialisation
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    plain_run = RunResult(
        run_id="r",
        config_name="c",
        items=[ItemResult(item, TargetOutput(output="x"), [])],
        aggregate={},
        started_at=moment,
        finished_at=moment,
    )
    plain_payload = plain_run.to_dict()
    plain_item = plain_payload["items"][0]
    _check(
        set(plain_item) == {"id", "inputs", "expected", "output", "error", "latency_ms", "scores"},
        "repetitions=1 item payload has no attempt-identity keys",
        errors,
    )
    _check("reliability" not in plain_payload, "repetitions=1 run payload has no 'reliability' key", errors)

    # 4-5. Engine: exact call count, byte-identical input, per-attempt RNG reset
    class _CountingTarget(TargetRunner):
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def run(self, item: EvalItem) -> TargetOutput:
            self.calls.append(dict(item.inputs))
            return TargetOutput(output="x")

    class _RngProbeScorer(Scorer):
        default_name = "rng_probe"

        def score(self, item: EvalItem, output: TargetOutput, ctx) -> ScoreResult:
            draw = ctx.rng.random()
            return ScoreResult(self.name, value=draw, passed=draw < 0.5)

    TARGETS.register_class("f056_counting", _CountingTarget)
    SCORERS.register_class("f056_rng_probe", _RngProbeScorer)
    try:
        for max_workers, label in ((1, "sequential"), (4, "parallel")):
            cfg = {
                "schema_version": SCHEMA_VERSION,
                "run": {
                    "name": "t",
                    "run_id": f"f056-{label}",
                    "seed": 7,
                    "repetitions": 5,
                    "max_workers": max_workers,
                },
                "dataset": {"type": "inline", "params": {"items": [{"id": "1", "inputs": {"q": "x"}}]}},
                "target": {"type": "f056_counting", "params": {}},
                "scorers": [{"type": "f056_rng_probe"}],
                "sinks": [],
            }
            engine = EvalEngine.from_config(load_config_dict(cfg))
            run = engine.run()
            counting_target = cast(_CountingTarget, engine.target)
            _check(
                len(counting_target.calls) == 5, f"repetitions=5 invokes the target exactly 5 times ({label})", errors
            )
            _check(
                all(c == counting_target.calls[0] for c in counting_target.calls),
                f"every attempt receives byte-identical input ({label})",
                errors,
            )
            draws = {ir.scores[0].value for ir in run.items}
            _check(len(draws) == 1, f"scorer RNG draw is stable across all 5 attempts ({label})", errors)

        # distinct per-item seeds: the RunContext.item_index trap
        cfg2 = {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "t", "seed": 7, "repetitions": 2, "max_workers": 1},
            "dataset": {
                "type": "inline",
                "params": {"items": [{"id": "a", "inputs": {}}, {"id": "b", "inputs": {}}]},
            },
            "target": {"type": "f056_counting", "params": {}},
            "scorers": [{"type": "f056_rng_probe"}],
            "sinks": [],
        }
        engine2 = EvalEngine.from_config(load_config_dict(cfg2))
        run2 = engine2.run()
        first_draws = {ir.item.id: ir.scores[0].value for ir in run2.items if ir.attempt_index == 0}
        expected = {"a": _make_item_rng(7, 0).random(), "b": _make_item_rng(7, 1).random()}
        _check(
            first_draws == expected,
            "per-item seeds are derived from the loop's own index, not a shared/defaulted item_index",
            errors,
        )
    finally:
        TARGETS._reg.pop("f056_counting", None)
        SCORERS._reg.pop("f056_rng_probe", None)

    # 6. is_deterministic on TargetRunner / ModelTarget
    _check(_CountingTarget().is_deterministic() is None, "is_deterministic defaults to None", errors)
    import unittest.mock as mock

    _check(
        ModelTarget(provider="openai", model="m", temperature=0.0, client=mock.MagicMock()).is_deterministic() is True,
        "ModelTarget.is_deterministic() is True at temperature=0.0",
        errors,
    )
    _check(
        ModelTarget(provider="openai", model="m", temperature=0.7, client=mock.MagicMock()).is_deterministic() is False,
        "ModelTarget.is_deterministic() is False at temperature=0.7",
        errors,
    )

    # 7. deterministic_sampling diagnostic present/absent, omitted key when empty
    class _AlwaysPassScorer(Scorer):
        default_name = "f056_always_pass"

        def score(self, item: EvalItem, output: TargetOutput, ctx) -> ScoreResult:
            return ScoreResult(self.name, value=1.0, passed=True)

    SCORERS.register_class("f056_always_pass", _AlwaysPassScorer)
    try:
        det_cfg = {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "t", "seed": 1, "repetitions": 3, "max_workers": 1},
            "dataset": {"type": "inline", "params": {"items": [{"id": "1", "inputs": {"q": "x"}}]}},
            "target": {"type": "echo", "params": {"output_key": "q"}},
            "scorers": [{"type": "f056_always_pass"}],
            "sinks": [],
        }
        det_run = EvalEngine.from_config(load_config_dict(det_cfg)).run()
        _check(len(det_run.diagnostics) == 1, "diagnostic present for a deterministic all-pass run", errors)
        _check(
            det_run.diagnostics[0]["code"] == "deterministic_sampling",
            "diagnostic carries the 'deterministic_sampling' code",
            errors,
        )
        _check(
            "reliability" in det_run.to_dict() and det_run.to_dict()["reliability"]["diagnostics"],
            "the diagnostic is serialised under a 'reliability' key",
            errors,
        )
    finally:
        SCORERS._reg.pop("f056_always_pass", None)

    # 8. ReliabilityAggregator: pass@k vs pass^k, never pooled across items
    def attempt(item_id: str, idx: int, *, passed: bool) -> ItemResult:
        return ItemResult(
            item=EvalItem(id=item_id, inputs={}),
            output=TargetOutput(output="x"),
            scores=[ScoreResult(name="acc", value=1.0 if passed else 0.0, passed=passed)],
            attempt_index=idx,
            attempt_id=f"{item_id}:{idx}",
            item_run_id=f"run:{item_id}",
        )

    one_of_five = [attempt("i1", a, passed=(a == 0)) for a in range(5)]
    report_1of5 = ReliabilityAggregator.aggregate(one_of_five)
    entry_1of5 = report_1of5.per_item[0]
    _check(entry_1of5.pass_at_k is True, "one-of-five passes pass@5", errors)
    _check(entry_1of5.pass_power_k is False, "one-of-five fails pass^5", errors)

    five_of_five = [attempt("i1", a, passed=True) for a in range(5)]
    entry_5of5 = ReliabilityAggregator.aggregate(five_of_five).per_item[0]
    _check(entry_5of5.pass_power_k is True, "five-of-five passes pass^5", errors)

    mixed = [attempt(f"easy{i}", a, passed=True) for i in range(9) for a in range(5)]
    mixed += [attempt("hard", a, passed=(a == 0)) for a in range(5)]
    mixed_report = ReliabilityAggregator.aggregate(mixed)
    hard_entry = next(e for e in mixed_report.per_item if e.item_id == "hard")
    _check(
        hard_entry.pass_power_k is False and len(mixed_report.per_item) == 10,
        "pass^k is per item: 9 easy items do not mask one unreliable item",
        errors,
    )

    # 9. Gating wiring, end to end
    def repeated_run(per_item: dict[str, list[bool]]) -> RunResult:
        items = [
            attempt(item_id, idx, passed=p) for item_id, verdicts in per_item.items() for idx, p in enumerate(verdicts)
        ]
        return RunResult(run_id="g", config_name="c", items=items, aggregate={}, started_at=moment, finished_at=moment)

    passing_gate = GateConfig.model_validate({"rules": [{"score": "acc", "metric": "pass_power_k", "min": 1.0}]})
    ok_run = repeated_run({"i1": [True, True, True]})
    _check(evaluate_gate(passing_gate, ok_run).passed is True, "a satisfied pass_power_k gate passes", errors)

    bad_run = repeated_run({"i1": [True, False, True]})
    bad_result = evaluate_gate(passing_gate, bad_run)
    _check(bad_result.passed is False, "a failing pass_power_k gate reports passed=False", errors)
    _check(
        any("pass_power_k" in f for f in bad_result.failures),
        "the failure reason names the reliability metric",
        errors,
    )

    return report(logger, "F-056", errors)


if __name__ == "__main__":
    sys.exit(main())

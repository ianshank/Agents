"""Trajectory scorers through the real engine and the real config loader.

The unit suites construct scorers directly via ``SCORERS.create``, which skips two
seams that a suite actually depends on: ``EvalConfig`` validation (a params typo or a
name that fails strict ``from_dict`` would go unnoticed) and ``EvalEngine.run`` (the
per-item ``RunContext``, the scorer try/except, aggregation, and sink emission).
Everything here is offline and deterministic — no judge, no network.
"""

from __future__ import annotations

import json
import logging

import pytest

from eval_harness.config import load_config, load_config_dict
from eval_harness.core.interfaces import TargetRunner
from eval_harness.core.types import AgentTrajectory, EvalItem, TargetOutput
from eval_harness.engine import EvalEngine
from eval_harness.plugins import SCORERS, TARGETS, bootstrap
from eval_harness.version import SCHEMA_VERSION
from tests._trajectory_helpers import final, observation, tool_call, tool_error

bootstrap()

#: Reference the fixture target satisfies exactly, for the happy path.
_REFERENCE = ["search", "fetch"]


class _TrajectoryTarget:
    """A deterministic target that emits a fixed trajectory. Registered per test."""

    def __init__(self, trajectory: AgentTrajectory, output: str = "answer") -> None:
        self._trajectory = trajectory
        self._output = output

    def run(self, item: EvalItem) -> TargetOutput:
        return TargetOutput(output=self._output, trajectory=self._trajectory)


def _engine(scorers: list, target: TargetRunner, items: list[EvalItem], sinks: list | None = None) -> EvalEngine:
    class _Dataset:
        def load(self):
            return items

    config = load_config_dict(
        {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "trajectory-e2e", "seed": 1},
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo", "params": {}},
            "scorers": [],
        }
    )
    return EvalEngine(config, dataset=_Dataset(), target=target, scorers=scorers, sinks=sinks or [])


# --- engine-level (F5) -------------------------------------------------------------


def test_trajectory_scorer_runs_through_the_engine():
    trajectory = AgentTrajectory(steps=(tool_call("search"), observation("hit"), tool_call("fetch"), final("done")))
    items = [EvalItem(id="i1", inputs={}, expected=_REFERENCE)]
    engine = _engine([SCORERS.create("trajectory_in_order", {})], _TrajectoryTarget(trajectory), items)

    run = engine.run()

    assert len(run.items) == 1
    score = run.items[0].scores[0]
    assert score.name == "trajectory_in_order"
    assert score.passed is True
    assert run.aggregate["trajectory_in_order"].pass_rate == 1.0


def test_engine_carries_the_trajectory_into_the_emitted_payload():
    trajectory = AgentTrajectory(steps=(tool_call("search", {"q": "x"}), final("done")))
    items = [EvalItem(id="i1", inputs={}, expected=["search"])]
    engine = _engine([SCORERS.create("trajectory_exact", {})], _TrajectoryTarget(trajectory), items)

    payload = engine.run().to_dict()

    emitted = payload["items"][0]["trajectory"]
    assert [step["kind"] for step in emitted["steps"]] == ["tool_call", "final"]
    # Must survive a real json round-trip: MappingProxyType is not JSON-native, so a
    # regression that leaked the proxy into the payload would fail here.
    assert json.loads(json.dumps(payload, default=str))["items"][0]["trajectory"] == emitted


def test_a_text_only_target_does_not_depress_the_engine_pass_rate():
    """The not-applicable contract, asserted where it actually matters: the aggregate."""

    class _TextTarget:
        def run(self, item: EvalItem) -> TargetOutput:
            return TargetOutput(output="plain text")

    items = [EvalItem(id=f"i{n}", inputs={}, expected=["search"]) for n in range(3)]
    engine = _engine([SCORERS.create("trajectory_exact", {})], _TextTarget(), items)

    run = engine.run()

    assert all(result.scores[0].passed is None for result in run.items)
    assert run.aggregate["trajectory_exact"].pass_rate is None, "no verdicts means no pass rate, not 0.0"


def test_engine_mixes_trajectory_and_text_scorers_on_one_item():
    trajectory = AgentTrajectory(steps=(tool_call("search"), final("done")))
    items = [EvalItem(id="i1", inputs={}, expected=["search"])]
    engine = _engine(
        [SCORERS.create("trajectory_exact", {}), SCORERS.create("contains", {"substring": "answer"})],
        _TrajectoryTarget(trajectory),
        items,
    )

    run = engine.run()

    assert {s.name: s.passed for s in run.items[0].scores} == {"trajectory_exact": True, "contains": True}


def test_a_scorer_error_does_not_abort_the_run():
    """The engine's per-item guard still applies to trajectory scorers."""

    class _Exploding:
        name = "boom"

        def score(self, item, output, ctx):
            raise RuntimeError("scorer blew up")

    trajectory = AgentTrajectory(steps=(tool_call("search"),))
    items = [EvalItem(id="i1", inputs={}, expected=["search"])]
    engine = _engine([_Exploding(), SCORERS.create("trajectory_exact", {})], _TrajectoryTarget(trajectory), items)

    run = engine.run()

    verdicts = {s.name: s.passed for s in run.items[0].scores}
    assert verdicts["boom"] is False
    assert verdicts["trajectory_exact"] is True


# --- config-driven (F6) ------------------------------------------------------------


def _config_with(scorer: dict) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {"name": "trajectory-config", "seed": 0},
        "dataset": {"type": "inline", "params": {"items": [{"id": "i1", "inputs": {}, "expected": ["search"]}]}},
        "target": {"type": "echo", "params": {}},
        "scorers": [scorer],
    }


@pytest.mark.parametrize(
    "scorer",
    [
        {"type": "trajectory_exact", "params": {}},
        {"type": "trajectory-in-order", "params": {}},
        {"type": "trajectory_precision_recall", "params": {"pass_threshold": 0.8}},
        {"type": "trajectory_step_efficiency", "params": {"budget": 4, "count": "steps"}},
        {"type": "trajectory_loop_detection", "params": {"max_repeats": 3, "consecutive": False}},
        {"type": "trajectory_recovery", "params": {"failure_key": "aborted"}},
        {"type": "trajectory_any_order", "params": {"ignore_fields": ["req_id"], "on_missing": 0.25}},
    ],
)
def test_every_trajectory_scorer_is_constructible_from_config(scorer):
    config = load_config_dict(_config_with(scorer))
    built = SCORERS.create(config.scorers[0].type, config.scorers[0].params)
    assert built.name.startswith("trajectory")


def test_config_loading_is_strict_about_unknown_scorer_params():
    config = load_config_dict(_config_with({"type": "trajectory_exact", "params": {"not_a_param": 1}}))
    with pytest.raises(TypeError):
        SCORERS.create(config.scorers[0].type, config.scorers[0].params)


def test_the_shipped_example_config_loads_and_builds():
    """`config/trajectory_eval.yaml` must stay runnable, not just illustrative."""
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "config" / "trajectory_eval.yaml"
    config = load_config(path)
    engine = EvalEngine.from_config(config)
    run = engine.run()
    assert run.items, "the example config must actually produce results"
    assert any(name.startswith("trajectory") for name in run.aggregate)


# --- composite interaction (F7) ----------------------------------------------------


def test_composite_ignores_a_not_applicable_verdict_but_not_its_value():
    """The surprising-but-intended interaction, pinned so it cannot drift silently.

    ``CompositeScorer`` drops ``passed=None`` from its verdict logic while still blending
    the child's *value* into the weighted mean. A trajectory child on a text-only target
    therefore contributes ``on_missing`` to the score and nothing to pass/fail.
    """
    composite = SCORERS.create(
        "weighted",
        {
            "components": [
                {"type": "contains", "params": {"substring": "answer"}, "weight": 1},
                {"type": "trajectory_exact", "params": {}, "weight": 1},
            ]
        },
    )
    items = [EvalItem(id="i1", inputs={}, expected=["search"])]

    class _TextTarget:
        def run(self, item: EvalItem) -> TargetOutput:
            return TargetOutput(output="answer")

    run = _engine([composite], _TextTarget(), items).run()
    score = run.items[0].scores[0]

    assert score.passed is True, "the None verdict is ignored, so the composite still passes"
    assert score.value == pytest.approx(0.5), "but on_missing=0.0 halves the value"


def test_composite_on_missing_is_tunable_to_avoid_depressing_the_score():
    composite = SCORERS.create(
        "weighted",
        {
            "components": [
                {"type": "contains", "params": {"substring": "answer"}, "weight": 1},
                {"type": "trajectory_exact", "params": {"on_missing": 1.0}, "weight": 1},
            ]
        },
    )

    class _TextTarget:
        def run(self, item: EvalItem) -> TargetOutput:
            return TargetOutput(output="answer")

    run = _engine([composite], _TextTarget(), [EvalItem(id="i1", inputs={}, expected=["search"])]).run()
    assert run.items[0].scores[0].value == pytest.approx(1.0)


# --- logging (F4) ------------------------------------------------------------------


def test_a_failed_match_logs_the_diverging_calls_at_debug(caplog):
    trajectory = AgentTrajectory(steps=(tool_call("wrong"), final("done")))
    items = [EvalItem(id="i1", inputs={}, expected=["search"])]
    engine = _engine([SCORERS.create("trajectory_exact", {})], _TrajectoryTarget(trajectory), items)

    with caplog.at_level(logging.DEBUG, logger="eval_harness.scorers.trajectory"):
        engine.run()

    assert any("wrong" in record.getMessage() for record in caplog.records)


def test_nothing_is_logged_at_the_default_level(caplog):
    trajectory = AgentTrajectory(steps=(tool_call("wrong"), final("done")))
    items = [EvalItem(id="i1", inputs={}, expected=["search"])]
    engine = _engine([SCORERS.create("trajectory_exact", {})], _TrajectoryTarget(trajectory), items)

    with caplog.at_level(logging.WARNING, logger="eval_harness.scorers.trajectory"):
        engine.run()

    assert not [r for r in caplog.records if r.name == "eval_harness.scorers.trajectory"]


def test_the_not_applicable_path_explains_itself_at_debug(caplog):
    class _TextTarget:
        def run(self, item: EvalItem) -> TargetOutput:
            return TargetOutput(output="plain")

    items = [EvalItem(id="i1", inputs={}, expected=["search"])]
    engine = _engine([SCORERS.create("trajectory_exact", {})], _TextTarget(), items)

    with caplog.at_level(logging.DEBUG, logger="eval_harness.scorers.trajectory"):
        engine.run()

    assert any("no trajectory" in (record.getMessage()) for record in caplog.records)


def test_recovery_logs_the_unrecovered_tool_names(caplog):
    trajectory = AgentTrajectory(steps=(tool_error("flaky"), final("all good")))
    items = [EvalItem(id="i1", inputs={}, expected=None)]
    engine = _engine([SCORERS.create("trajectory_recovery", {})], _TrajectoryTarget(trajectory), items)

    with caplog.at_level(logging.DEBUG, logger="eval_harness.scorers.trajectory"):
        engine.run()

    assert any("flaky" in (record.getMessage()) for record in caplog.records)


# --- targets registry sanity -------------------------------------------------------


def test_builtin_targets_still_emit_no_trajectory():
    """Backwards compatibility: echo/callable are untouched by F-051."""
    echo = TARGETS.create("echo", {})
    assert echo.run(EvalItem(id="i", inputs={"x": 1})).trajectory is None


# --- CallableTarget TargetOutput pass-through --------------------------------------
#
# Without this, no built-in target can emit a trajectory and F-051 is unreachable from a
# YAML config without writing a bespoke TargetRunner.


def test_callable_target_passes_through_a_target_output_with_its_trajectory():
    target = TARGETS.create("callable", {"path": "tests._sut:trajectory_demo"})
    result = target.run(EvalItem(id="i", inputs={"question": "what is widget 42"}))
    assert result.trajectory is not None
    assert [c.name for c in result.trajectory.tool_calls()] == ["search", "fetch"]


def test_callable_target_fills_in_latency_when_the_callable_did_not():
    target = TARGETS.create("callable", {"path": "tests._sut:trajectory_demo"})
    result = target.run(EvalItem(id="i", inputs={}))
    assert result.latency_ms is not None and result.latency_ms >= 0.0


def test_callable_target_preserves_a_latency_the_callable_measured_itself():
    target = TARGETS.create("callable", {"path": "tests._sut:preset_latency_output"})
    assert target.run(EvalItem(id="i", inputs={})).latency_ms == 123.5


def test_callable_target_still_wraps_a_plain_return_value():
    """Backwards compatibility: callables returning a scalar are untouched."""
    target = TARGETS.create("callable", {"path": "tests._sut:summarize"})
    result = target.run(EvalItem(id="i", inputs={"text": "hello"}))
    assert result.output == "summary: hello"
    assert result.trajectory is None


def test_callable_target_errors_still_surface_as_scored_errors():
    target = TARGETS.create("callable", {"path": "tests._sut:boom"})
    result = target.run(EvalItem(id="i", inputs={}))
    assert result.error is not None and result.output is None

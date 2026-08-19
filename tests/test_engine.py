from __future__ import annotations

from datetime import UTC, datetime

from eval_harness.config import load_config_dict
from eval_harness.core.types import EvalItem, ScoreResult, TargetOutput
from eval_harness.engine import EvalEngine
from eval_harness.gating import evaluate_gate
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.version import SCHEMA_VERSION


def _fixed_clock():
    return datetime(2026, 1, 1, tzinfo=UTC)


CONFIG = {
    "schema_version": SCHEMA_VERSION,
    "run": {"name": "t", "run_id": "fixed-1", "seed": 1},
    "dataset": {
        "type": "inline",
        "params": {
            "items": [
                {"id": "1", "inputs": {"q": "reset password"}, "expected": "reset password"},
                {"id": "2", "inputs": {"q": "cancel plan"}, "expected": "cancel plan"},
            ]
        },
    },
    "target": {"type": "echo", "params": {"output_key": "q"}},
    "scorers": [
        {"type": "exact_match", "params": {"name": "acc"}},
        {"type": "contains", "params": {"name": "has_reset", "substring": "reset"}},
        {"type": "llm_judge", "params": {"name": "quality", "threshold": 0.6}},
    ],
    "judge": {"type": "mock", "params": {"default_score": 0.8}},
    "sinks": [{"type": "langfuse", "params": {}}],
}


def _engine(cfg=None, client=None):
    config = load_config_dict(cfg or dict(CONFIG))
    engine = EvalEngine.from_config(config, langfuse_client=client or NullLangfuseClient())
    engine.clock = _fixed_clock
    return config, engine


def test_engine_end_to_end_aggregate(caplog):
    _, engine = _engine()
    with caplog.at_level("DEBUG", logger="eval_harness.engine"):
        run = engine.run()
    assert run.run_id == "fixed-1"
    assert len(run.items) == 2
    # exact_match: both outputs equal expected -> mean 1.0
    assert run.aggregate["acc"].mean == 1.0
    # contains 'reset': only item 1 -> pass_rate 0.5
    assert run.aggregate["has_reset"].pass_rate == 0.5
    # item 1: has_reset passes, judge runs -> 0.8. item 2: has_reset fails, so the
    # judge is skipped entirely (F-057: a judge can't convert an already-failed item
    # into a pass) and contributes no ScoreResult at all -> mean is 0.8 over the one
    # item actually judged, not diluted by a synthetic value for the skipped one.
    assert abs(run.aggregate["quality"].mean - 0.8) < 1e-9
    assert run.aggregate["quality"].count == 1
    # The skip is diagnosable, not silent: a debug log names the item and scorer.
    assert any("skipping judge scorer" in r.message and "quality" in r.message for r in caplog.records)


def test_a_judge_scorer_error_does_not_skip_a_later_judge_scorer():
    """A judge-backed scorer's own exception is a real failure, not a routing
    signal — it must not trip the F-057 skip-later-judges guard, which exists
    only for a *programmatic* scorer having already failed the item."""

    class _Dataset:
        def load(self):
            return [EvalItem(id="i1", inputs={})]

    class _EchoTarget:
        def run(self, item):
            return TargetOutput(output="ok")

    class _ExplodingJudge:
        name = "judge_a"

        def uses_judge(self) -> bool:
            return True

        def score(self, item, output, ctx):
            raise RuntimeError("judge blew up")

    class _OkJudge:
        name = "judge_b"

        def uses_judge(self) -> bool:
            return True

        def score(self, item, output, ctx):
            return ScoreResult(name=self.name, value=1.0, passed=True)

    config = load_config_dict(dict(CONFIG))
    engine = EvalEngine(
        config,
        dataset=_Dataset(),
        target=_EchoTarget(),
        scorers=[_ExplodingJudge(), _OkJudge()],
        sinks=[],
    )

    run = engine.run()

    verdicts = {s.name: s.passed for s in run.items[0].scores}
    assert verdicts["judge_a"] is False
    assert verdicts["judge_b"] is True


def test_engine_writes_scores_to_langfuse():
    client = NullLangfuseClient()
    _, engine = _engine(client=client)
    engine.run()
    # 3 scorers x 2 items = 6, minus 1: item 2 fails has_reset (a programmatic
    # scorer), so its judge scorer is skipped entirely rather than scored (F-057).
    assert len(client.scores) == 5
    assert client.flushed


def test_sampling_zero_rate_empty():
    cfg = dict(CONFIG)
    cfg["run"] = {"name": "t", "run_id": "z", "seed": 1, "sample_rate": 0.0}
    _, engine = _engine(cfg)
    run = engine.run()
    assert run.items == []


def test_sampling_is_deterministic():
    cfg = dict(CONFIG)
    cfg["run"] = {"name": "t", "seed": 42, "sample_rate": 0.5}
    runs = []
    for _ in range(2):
        _, engine = _engine(dict(cfg))
        runs.append([ir.item.id for ir in engine.run().items])
    assert runs[0] == runs[1]  # same seed -> same sample


def test_gate_pass():
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "acc", "metric": "mean", "min": 0.9}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert result.passed


def test_gate_fail():
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "has_reset", "metric": "pass_rate", "min": 0.9}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert not result.passed and result.failures


def test_gate_missing_score():
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "nope", "metric": "mean", "min": 0.1}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert not result.passed


def test_gate_none_passes():
    _config, engine = _engine()
    assert evaluate_gate(None, engine.run()).passed


def test_gate_pass_rate_none_fails():
    """Metric='pass_rate' on an aggregate with pass_rate=None → failure with informative message."""

    from eval_harness.config.models import GateConfig, GateRule
    from eval_harness.core.types import RunResult, ScoreAggregate

    run = RunResult(
        run_id="r",
        config_name="c",
        items=[],
        aggregate={"acc": ScoreAggregate(count=1, mean=0.9, pass_rate=None)},
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    gate = GateConfig(rules=[GateRule(score="acc", metric="pass_rate", min=0.5)])
    result = evaluate_gate(gate, run)
    assert not result.passed
    assert any("pass_rate" in f for f in result.failures)


def test_gate_max_violated_fails():
    """A rule with max=0.5 fails when observed mean=1.0 exceeds it."""
    cfg = dict(CONFIG)
    cfg["gate"] = {"rules": [{"score": "acc", "metric": "mean", "max": 0.5}]}
    config, engine = _engine(cfg)
    result = evaluate_gate(config.gate, engine.run())
    assert not result.passed
    assert any("above max" in f for f in result.failures)

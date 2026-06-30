from __future__ import annotations

import pytest

from eval_harness.core.types import EvalItem, RunContext, TargetOutput
from eval_harness.judges import MockJudge
from eval_harness.plugins import SCORERS


def _ctx(judge=None):
    return RunContext(config=None, judge=judge)


def _item(expected=None, **inputs):
    return EvalItem(id="i", inputs=inputs, expected=expected)


def test_registered_with_aliases():
    assert "weighted" in SCORERS
    for alias in ("composite", "ensemble"):
        assert alias in SCORERS
        assert SCORERS.resolve(alias) == "weighted"


def test_weighted_mean_unequal_weights():
    s = SCORERS.create(
        "weighted",
        {
            "components": [
                {"type": "contains", "params": {"substring": "ok"}, "weight": 3},
                {"type": "exact_match", "params": {}, "weight": 1},
            ]
        },
    )
    r = s.score(_item(expected="nope"), TargetOutput(output="ok"), _ctx())
    assert r.value == pytest.approx(0.75)
    assert [c["weight"] for c in r.metadata["components"]] == [3.0, 1.0]
    assert r.metadata["strategy"] == "weighted_mean"


def test_default_weight_is_one():
    s = SCORERS.create(
        "weighted",
        {
            "components": [
                {"type": "contains", "params": {"substring": "a"}},
                {"type": "contains", "params": {"substring": "z"}},
            ]
        },
    )
    r = s.score(_item(), TargetOutput(output="a"), _ctx())
    # one child 1.0, other 0.0, equal default weights -> 0.5
    assert r.value == pytest.approx(0.5)


def test_single_component():
    s = SCORERS.create("composite", {"components": [{"type": "exact_match", "params": {}}]})
    r = s.score(_item(expected="x"), TargetOutput(output="x"), _ctx())
    assert r.value == 1.0


def test_pass_threshold_true_and_false():
    spec = {"components": [{"type": "contains", "params": {"substring": "ok"}}]}
    high = SCORERS.create("weighted", {**spec, "pass_threshold": 0.5})
    assert high.score(_item(), TargetOutput(output="ok"), _ctx()).passed is True
    low = SCORERS.create("weighted", {**spec, "pass_threshold": 0.5})
    assert low.score(_item(), TargetOutput(output="no"), _ctx()).passed is False


def test_pass_threshold_boundary_inclusive():
    s = SCORERS.create(
        "weighted",
        {"components": [{"type": "contains", "params": {"substring": "ok"}}], "pass_threshold": 1.0},
    )
    # value exactly 1.0 >= threshold 1.0 -> passed
    assert s.score(_item(), TargetOutput(output="ok"), _ctx()).passed is True


def test_no_threshold_aggregates_child_passed():
    # both children pass -> composite passed True
    s = SCORERS.create(
        "weighted",
        {
            "components": [
                {"type": "contains", "params": {"substring": "o"}},
                {"type": "contains", "params": {"substring": "k"}},
            ]
        },
    )
    assert s.score(_item(), TargetOutput(output="ok"), _ctx()).passed is True
    # one child fails -> composite passed False
    s2 = SCORERS.create(
        "weighted",
        {
            "components": [
                {"type": "contains", "params": {"substring": "o"}},
                {"type": "contains", "params": {"substring": "z"}},
            ]
        },
    )
    assert s2.score(_item(), TargetOutput(output="ok"), _ctx()).passed is False


def test_no_threshold_all_none_yields_none():
    # regex scorer always sets passed bool, so use a child returning passed=None:
    # llm_judge sets passed bool too. Use a custom: contains sets bool. To get
    # None we rely on a scorer whose passed is None — none builtin does that,
    # so simulate via a single component and monkeypatch-free path: the
    # aggregate of an empty verdict list returns None. Build a composite whose
    # only child reports None by using a stub registered scorer.
    from eval_harness.core.interfaces import Scorer
    from eval_harness.core.types import ScoreResult

    class _NoneScorer(Scorer):
        default_name = "noneish"

        def score(self, item, output, ctx):
            return ScoreResult(self.name, value=0.4, passed=None)

    SCORERS.register_class("noneish", _NoneScorer)
    try:
        s = SCORERS.create("weighted", {"components": [{"type": "noneish"}]})
        r = s.score(_item(), TargetOutput(output="x"), _ctx())
        assert r.passed is None
        assert r.value == pytest.approx(0.4)
    finally:
        SCORERS._reg.pop("noneish", None)


def test_llm_judge_child_receives_ctx_judge():
    s = SCORERS.create(
        "weighted",
        {"components": [{"type": "llm_judge", "params": {"threshold": 0.5}}]},
    )
    judge = MockJudge(default_score=0.9)
    r = s.score(_item(expected="x"), TargetOutput(output="y"), _ctx(judge=judge))
    assert r.value == pytest.approx(0.9)


def test_unknown_child_type_raises():
    from eval_harness.core.registry import RegistryError

    with pytest.raises(RegistryError):
        SCORERS.create("weighted", {"components": [{"type": "does_not_exist"}]})


def test_empty_components_raises():
    with pytest.raises(ValueError, match="at least one component"):
        SCORERS.create("weighted", {"components": []})
    with pytest.raises(ValueError, match="at least one component"):
        SCORERS.create("weighted", {})


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="unknown strategy"):
        SCORERS.create("weighted", {"components": [{"type": "contains", "params": {}}], "strategy": "geomean"})


def test_negative_weight_raises():
    with pytest.raises(ValueError, match="weight must be >= 0"):
        SCORERS.create("weighted", {"components": [{"type": "contains", "params": {}, "weight": -1}]})


def test_zero_total_weight_raises():
    with pytest.raises(ValueError, match="total weight must be > 0"):
        SCORERS.create(
            "weighted",
            {
                "components": [
                    {"type": "contains", "params": {}, "weight": 0},
                    {"type": "exact_match", "params": {}, "weight": 0},
                ]
            },
        )


def test_custom_component_name_label():
    s = SCORERS.create(
        "weighted",
        {"components": [{"type": "contains", "params": {"substring": "a"}, "name": "has_a"}]},
    )
    r = s.score(_item(), TargetOutput(output="a"), _ctx())
    assert r.metadata["components"][0]["name"] == "has_a"


def test_breakdown_survives_to_dict_roundtrip():
    from datetime import datetime, timezone

    from eval_harness.core.types import ItemResult, RunResult, ScoreAggregate

    s = SCORERS.create("weighted", {"components": [{"type": "contains", "params": {"substring": "a"}}]})
    item = _item()
    out = TargetOutput(output="a")
    res = s.score(item, out, _ctx())
    run = RunResult(
        run_id="r",
        config_name="c",
        items=[ItemResult(item=item, output=out, scores=[res])],
        aggregate={"weighted": ScoreAggregate(count=1, mean=res.value, pass_rate=1.0)},
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    dumped = run.to_dict()["items"][0]["scores"][0]
    assert dumped["metadata"]["components"][0]["name"]

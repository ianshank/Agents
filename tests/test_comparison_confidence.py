"""Tests for the confidence-aware side of F-024's multi-model comparison.

The existing ``tests/test_comparison.py`` covers the point-estimate contract
(values / deltas / ranking / CLI); this file covers the additive uncertainty
layer: Wilson intervals per model, a ranking that refuses to order overlapping
intervals, the ``min_sample`` power floor, the ``mean``-is-not-a-proportion
carve-out, and the HTML report's rendering of all of it.

Deterministic and fully offline: the interval maths is exercised against
hand-built :class:`RunResult` fixtures (no engine, no clock, no I/O), and the
end-to-end cases reuse the same deterministic ``echo`` targets as
``test_comparison.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from eval_harness.comparison import (
    ComparisonResult,
    MetricComparison,
    RankConfidenceConfig,
    RankVerdict,
    compare_metric,
    run_comparison,
)
from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    RunResult,
    ScoreAggregate,
    ScoreResult,
    TargetOutput,
)
from eval_harness.version import SCHEMA_VERSION

FIXED = datetime(2026, 9, 4, tzinfo=UTC)
SCORE = "exact_match"

# A floor low enough that the small hand-built fixtures below are "powered", so
# the power-floor tests are the only ones that exercise the cant_tell branch.
_POWERED = RankConfidenceConfig(min_sample=10)


# --- fixtures ---------------------------------------------------------------


def _run(name: str, passes: int, n: int, *, score: str = SCORE, value: float | None = None) -> RunResult:
    """A synthetic RunResult with ``passes``/``n`` on ``score``.

    ``value`` overrides the per-item score value so ``mean`` can be varied
    independently of ``pass_rate``; by default value mirrors passed.
    """
    items: list[ItemResult] = []
    for i in range(n):
        passed = i < passes
        v = float(passed) if value is None else value
        items.append(
            ItemResult(
                item=EvalItem(id=f"{name}-{i}", inputs={}),
                output=TargetOutput(output=""),
                scores=[ScoreResult(name=score, value=v, passed=passed)],
            )
        )
    mean = (sum(s.value for ir in items for s in ir.scores) / n) if n else 0.0
    aggregate = {score: ScoreAggregate(count=n, mean=mean, pass_rate=(passes / n) if n else None)}
    return RunResult(
        run_id=name,
        config_name="cmp",
        items=items,
        aggregate=aggregate,
        started_at=FIXED,
        finished_at=FIXED,
    )


def _empty_run(name: str) -> RunResult:
    """A run that emitted no scores at all — the `None`-value case."""
    return RunResult(
        run_id=name,
        config_name="cmp",
        items=[],
        aggregate={},
        started_at=FIXED,
        finished_at=FIXED,
    )


def _config(n_items: int = 1, **comparison: Any) -> Any:
    """The same deterministic two-echo-model setup as ``tests/test_comparison.py``.

    "good" echoes the field matching ``expected`` (every item passes), "bad"
    echoes the other (every item fails).
    """
    from eval_harness.config.models import EvalConfig

    items = [{"id": str(i), "inputs": {"a": "x", "b": "y"}, "expected": "x"} for i in range(n_items)]
    return EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "cmp"},
            "dataset": {"type": "inline", "params": {"items": items}},
            "target": {"type": "echo", "params": {}},
            "scorers": [{"type": "exact_match", "params": {}}],
            "comparison": {
                "models": [
                    {"name": "good", "target": {"type": "echo", "params": {"output_key": "a"}}},
                    {"name": "bad", "target": {"type": "echo", "params": {"output_key": "b"}}},
                ],
                **comparison,
            },
        }
    )


# --- a clearly-better model is ranked first ---------------------------------


def test_clearly_better_model_is_ranked_first():
    runs = [("weak", _run("weak", 10, 100)), ("strong", _run("strong", 90, 100))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)

    assert cmp.verdict is RankVerdict.RANKED
    assert cmp.confident_ranking == [["strong"], ["weak"]]
    assert cmp.ranking == ["strong", "weak"]  # point-estimate order unchanged


def test_wilson_interval_is_reused_not_reinvented():
    from agent_core.calibration import wilson_interval

    runs = [("m", _run("m", 30, 50))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    st = cmp.stats["m"]

    assert (st.successes, st.n, st.interval) == (30, 50, "wilson")
    assert (st.ci_low, st.ci_high) == wilson_interval(30, 50, _POWERED.wilson_z)


# --- noise is not a winner ---------------------------------------------------


def test_noise_level_difference_on_small_sample_is_not_a_winner():
    # 26/50 vs 25/50 -> a 2-point point-estimate lead, wildly overlapping CIs.
    runs = [("a", _run("a", 26, 50)), ("b", _run("b", 25, 50))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)

    assert cmp.values == {"a": 0.52, "b": 0.5}
    assert cmp.ranking == ["a", "b"]  # the point estimate still orders them
    assert cmp.verdict is RankVerdict.NO_DIFFERENCE
    assert cmp.confident_ranking == [["a", "b"]]  # one tier -> no ordering claimed


def test_same_gap_becomes_significant_with_enough_samples():
    # The same 2-point gap, but 400x the data: now the intervals separate.
    runs = [("a", _run("a", 10400, 20000)), ("b", _run("b", 10000, 20000))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    assert cmp.verdict is RankVerdict.RANKED
    assert cmp.confident_ranking == [["a"], ["b"]]


def test_middle_model_overlapping_both_stays_untiered():
    # top clearly beats bottom, but the middle overlaps both -> a single tier,
    # because a boundary is only opened where the whole upper group beats
    # everything below it.
    runs = [
        ("top", _run("top", 70, 100)),
        ("mid", _run("mid", 55, 100)),
        ("bot", _run("bot", 40, 100)),
    ]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    assert cmp.ranking == ["top", "mid", "bot"]
    assert cmp.verdict is RankVerdict.NO_DIFFERENCE
    assert cmp.confident_ranking == [["top", "mid", "bot"]]


def test_tier_groups_tied_leaders_above_a_clear_loser():
    runs = [
        ("a", _run("a", 95, 100)),
        ("b", _run("b", 93, 100)),
        ("c", _run("c", 10, 100)),
    ]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    assert cmp.verdict is RankVerdict.RANKED
    assert cmp.confident_ranking == [["a", "b"], ["c"]]  # a and b left unordered


# --- ties --------------------------------------------------------------------


def test_exact_tie_claims_no_ordering():
    runs = [("first", _run("first", 50, 100)), ("second", _run("second", 50, 100))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)

    assert cmp.values == {"first": 0.5, "second": 0.5}
    # `ranking` still lists both (its tie order is the historical one and is left
    # exactly as it was); the honest output is that neither is above the other.
    assert set(cmp.ranking) == {"first", "second"}
    assert cmp.verdict is RankVerdict.NO_DIFFERENCE
    assert len(cmp.confident_ranking) == 1
    assert set(cmp.confident_ranking[0]) == {"first", "second"}


# --- the power floor ---------------------------------------------------------


def test_below_power_floor_makes_no_claim():
    # A perfect 8/8 vs 0/8 sweep — but 8 < min_sample, so no claim is made.
    runs = [("hi", _run("hi", 8, 8)), ("lo", _run("lo", 0, 8))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=RankConfidenceConfig(min_sample=30))

    assert cmp.verdict is RankVerdict.CANT_TELL
    assert cmp.confident_ranking == []
    assert cmp.min_sample == 30
    assert cmp.ranking == ["hi", "lo"]  # point estimates still reported


def test_one_model_below_floor_blocks_the_whole_claim():
    runs = [("hi", _run("hi", 95, 100)), ("lo", _run("lo", 1, 5))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=RankConfidenceConfig(min_sample=30))
    assert cmp.verdict is RankVerdict.CANT_TELL
    assert cmp.confident_ranking == []


def test_power_floor_is_config_not_a_literal():
    runs = [("hi", _run("hi", 40, 40)), ("lo", _run("lo", 0, 40))]
    assert compare_metric(runs, SCORE, "pass_rate", confidence=RankConfidenceConfig(min_sample=41)).verdict is (
        RankVerdict.CANT_TELL
    )
    assert compare_metric(runs, SCORE, "pass_rate", confidence=RankConfidenceConfig(min_sample=40)).verdict is (
        RankVerdict.RANKED
    )


def test_default_confidence_config_documents_its_defaults():
    conf = RankConfidenceConfig()
    assert (conf.min_sample, conf.wilson_z) == (30, 1.96)  # mirrors ABCampaignConfig


def test_wider_interval_is_harder_to_separate():
    runs = [("hi", _run("hi", 62, 100)), ("lo", _run("lo", 38, 100))]
    narrow = compare_metric(runs, SCORE, "pass_rate", confidence=RankConfidenceConfig(min_sample=10, wilson_z=1.0))
    wide = compare_metric(runs, SCORE, "pass_rate", confidence=RankConfidenceConfig(min_sample=10, wilson_z=3.5))
    assert narrow.verdict is RankVerdict.RANKED
    assert wide.verdict is RankVerdict.NO_DIFFERENCE


# --- a model missing a score entirely (today's None handling) ----------------


def test_missing_score_is_ranked_last_and_excluded_from_the_claim():
    runs = [("hi", _run("hi", 95, 100)), ("gone", _empty_run("gone")), ("lo", _run("lo", 5, 100))]
    cmp = compare_metric(runs, SCORE, "pass_rate", baseline="hi", confidence=_POWERED)

    assert cmp.values == {"hi": 0.95, "gone": None, "lo": 0.05}
    assert cmp.deltas["gone"] is None
    assert cmp.ranking == ["hi", "lo", "gone"]  # None last, unchanged behaviour
    # "gone" has no evidence, so it is neither ranked nor allowed to block a claim.
    assert cmp.verdict is RankVerdict.RANKED
    assert cmp.confident_ranking == [["hi"], ["lo"]]


def test_a_value_without_an_interval_never_yields_an_ordering():
    # Unreachable through the public API (the pass_rate path always produces an
    # interval); asserted directly so the invariant behind the defensive branch
    # is documented rather than assumed.
    from eval_harness.comparison import ModelStats, _rank_confidently

    stats = {
        "a": ModelStats("a", 0.9, None, 100, None, None, "none"),
        "b": ModelStats("b", 0.1, None, 100, None, None, "none"),
    }
    assert _rank_confidently(["a", "b"], stats, "pass_rate", 10) == (RankVerdict.NO_INTERVAL, [])


def test_no_model_has_the_score_makes_no_claim():
    runs = [("a", _empty_run("a")), ("b", _empty_run("b"))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    assert cmp.verdict is RankVerdict.CANT_TELL
    assert cmp.confident_ranking == []


def test_pass_rate_denominator_ignores_unscored_passes():
    # An item whose scorer returned passed=None must not inflate n (this is the
    # `pass_counts` semantics that ScoreAggregate.count would get wrong).
    run = _run("m", 5, 10)  # items 0-4 pass, 5-9 fail
    run.items[9].scores[0].passed = None
    cmp = compare_metric([("m", run)], SCORE, "pass_rate", confidence=_POWERED)
    assert cmp.stats["m"].n == 9
    assert cmp.stats["m"].successes == 5


# --- mean vs pass_rate --------------------------------------------------------


def test_mean_gets_no_binomial_interval():
    runs = [("hi", _run("hi", 100, 100, value=9.5)), ("lo", _run("lo", 0, 100, value=1.5))]
    cmp = compare_metric(runs, SCORE, "mean", confidence=_POWERED)

    assert cmp.values == {"hi": 9.5, "lo": 1.5}
    assert cmp.ranking == ["hi", "lo"]  # point-estimate ranking is still produced
    assert cmp.verdict is RankVerdict.NO_INTERVAL
    assert cmp.confident_ranking == []
    for st in cmp.stats.values():
        assert st.interval == "none"
        assert (st.ci_low, st.ci_high, st.successes) == (None, None, None)
        assert st.n == 100  # the sample size is still reported honestly


def test_pass_rate_and_mean_on_the_same_runs_differ_in_treatment():
    runs = [("hi", _run("hi", 90, 100)), ("lo", _run("lo", 10, 100))]
    by_rate = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    by_mean = compare_metric(runs, SCORE, "mean", confidence=_POWERED)

    assert by_rate.verdict is RankVerdict.RANKED
    assert by_mean.verdict is RankVerdict.NO_INTERVAL
    assert by_rate.stats["hi"].interval == "wilson"
    assert by_mean.stats["hi"].interval == "none"


def test_mean_does_not_import_agent_core(monkeypatch):
    # agent-core is not a runtime dependency, so the mean path must not need it.
    import sys

    monkeypatch.setitem(sys.modules, "agent_core.calibration", None)
    cmp = compare_metric([("m", _run("m", 5, 10, value=0.5))], SCORE, "mean", confidence=_POWERED)
    assert cmp.verdict is RankVerdict.NO_INTERVAL


# --- backwards compatibility --------------------------------------------------


def test_existing_to_dict_keys_are_unchanged_and_new_ones_are_additive():
    runs = [("hi", _run("hi", 90, 100)), ("lo", _run("lo", 10, 100))]
    d = compare_metric(runs, SCORE, "pass_rate", baseline="hi", confidence=_POWERED).to_dict()

    assert d["score"] == SCORE
    assert d["metric"] == "pass_rate"
    assert d["values"] == {"hi": 0.9, "lo": 0.1}
    assert d["deltas"] == {"hi": 0.0, "lo": -0.8}
    assert d["ranking"] == ["hi", "lo"]
    assert d["verdict"] == "ranked"
    assert d["confident_ranking"] == [["hi"], ["lo"]]
    assert d["stats"]["hi"]["n"] == 100
    json.dumps(d)  # still JSON-serialisable


def test_metric_comparison_constructs_without_the_new_fields():
    # The four historical fields remain sufficient; the no-claim verdict is the
    # honest default for a hand-built comparison carrying no evidence.
    cmp = MetricComparison(score="s", metric="mean", values={}, deltas={}, ranking=[])
    assert cmp.verdict is RankVerdict.CANT_TELL
    assert cmp.confident_ranking == []
    assert cmp.to_dict()["ranking"] == []


def test_run_comparison_still_ranks_on_point_estimates():
    result = run_comparison(_config(baseline="good"))
    assert isinstance(result, ComparisonResult)
    assert result.overall_ranking == ["good", "bad"]
    # Default rank_metric is "mean" -> no proportion interval applies.
    assert result.overall_verdict is RankVerdict.NO_INTERVAL
    assert result.to_dict()["overall_verdict"] == "no_interval"


def test_run_comparison_pass_rate_on_one_item_cannot_tell():
    result = run_comparison(_config(rank_metric="pass_rate"))
    assert result.overall_ranking == ["good", "bad"]  # 1.0 vs 0.0 point estimates
    assert result.overall_verdict is RankVerdict.CANT_TELL  # n=1 << min_sample
    assert result.overall_confident_ranking == []


def test_run_comparison_with_an_unknown_rank_by_claims_nothing():
    result = run_comparison(_config(n_items=40, rank_metric="pass_rate", rank_by="not_a_score"))
    assert result.overall_ranking == []
    assert result.overall_verdict is RankVerdict.CANT_TELL
    assert result.overall_confident_ranking == []


def test_run_comparison_accepts_an_injected_confidence_config():
    cfg = _config(n_items=40, rank_metric="pass_rate")
    blocked = run_comparison(cfg, confidence=RankConfidenceConfig(min_sample=50))
    powered = run_comparison(cfg, confidence=RankConfidenceConfig(min_sample=10))

    assert blocked.overall_verdict is RankVerdict.CANT_TELL
    assert blocked.overall_confident_ranking == []
    assert powered.overall_verdict is RankVerdict.RANKED
    assert powered.overall_confident_ranking == [["good"], ["bad"]]


# --- HTML report --------------------------------------------------------------


def _html_for(cmp: MetricComparison, **kwargs: Any) -> str:
    result = ComparisonResult(
        runs=[],
        comparisons=[cmp],
        rank_by=cmp.score,
        rank_metric=cmp.metric,
        overall_ranking=cmp.ranking,
        overall_verdict=cmp.verdict,
        overall_confident_ranking=cmp.confident_ranking,
        **kwargs,
    )
    return result.to_html()


def test_html_ranking_separator_is_not_double_escaped():
    runs = [("hi", _run("hi", 90, 100)), ("lo", _run("lo", 10, 100))]
    html = _html_for(compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED))

    assert "hi &gt; lo" in html
    assert "&amp;gt;" not in html  # the old double-escape rendered a literal "&gt;"


def test_html_escapes_model_names():
    runs = [("<script>", _run("<script>", 90, 100)), ("safe", _run("safe", 10, 100))]
    html = _html_for(compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_html_surfaces_intervals_and_verdict():
    runs = [("hi", _run("hi", 90, 100)), ("lo", _run("lo", 10, 100))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    html = _html_for(cmp)

    assert "ranked" in html
    assert "<th>CI</th>" in html and "<th>n</th>" in html
    assert "[0.826, 0.945]" in html  # Wilson CI for 90/100 at z=1.96
    assert f"[{cmp.stats['lo'].ci_low:.3f}, {cmp.stats['lo'].ci_high:.3f}]" in html
    assert "min_sample=10" in html


def test_html_says_no_interval_for_mean():
    runs = [("hi", _run("hi", 90, 100, value=7.0)), ("lo", _run("lo", 10, 100, value=1.0))]
    html = _html_for(compare_metric(runs, SCORE, "mean", confidence=_POWERED))
    assert "no_interval" in html
    assert "no sound interval for this statistic" in html


def test_html_is_deterministic_and_offline():
    runs = [("hi", _run("hi", 90, 100)), ("lo", _run("lo", 10, 100))]
    cmp = compare_metric(runs, SCORE, "pass_rate", confidence=_POWERED)
    assert _html_for(cmp) == _html_for(cmp)
    assert "http://" not in _html_for(cmp) and "https://" not in _html_for(cmp)

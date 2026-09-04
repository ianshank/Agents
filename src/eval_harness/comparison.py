"""Multi-model comparison (F-024).

Runs the same dataset/scorers/judge against several targets and produces a
comparative result: per-metric values, deltas vs a baseline, and a ranking.

Reuses the existing machinery rather than duplicating it: each model is a normal
single-target run through :class:`~eval_harness.engine.EvalEngine`, so all
scoring/aggregation/parallelism behaviour is identical to a one-model run. The
small :func:`compare_metric` primitive (per-metric values + deltas + ranking) is
shared with the A/B campaign feature (F-025).

**Uncertainty.** A raw point-estimate ranking over-claims: on a 50-item dataset a
2% pass-rate difference is noise, yet a sorted list presents it as a winner. So
the ranking is now *confidence-aware*, on exactly the convention F-025 already
uses (:mod:`eval_harness.campaign`, ADR 0012), and significance is **never
claimed below the configured power floor**:

  * ``agent_core.calibration.wilson_interval`` supplies the per-model CI — reused
    via the permitted ``eval_harness -> agent_core`` edge, never reimplemented.
    Imported lazily inside the function exactly as ``campaign._arm_stats`` does,
    because ``agent-core`` is **not** a runtime dependency of this package (see
    ``pyproject.toml``): importing this module, and the whole point-estimate
    path, must keep working when the sibling package is absent.
  * ``campaign.pass_counts`` supplies the (successes, n) pair, so the interval's
    denominator matches ``pass_rate`` semantics exactly rather than drifting from
    it (``ScoreAggregate.count`` counts scores whose ``passed`` is ``None`` too,
    and is therefore the wrong ``n``).
  * A ``mean`` is an arbitrary-range average, not a proportion, so a binomial
    interval is invalid for it. Rather than inventing one, the verdict is
    ``no_interval`` — the same spirit as ``cant_tell``.

Backwards compatible: this is an additive, opt-in entry point; the single-run
path is untouched, ``SCHEMA_VERSION`` is unchanged, and ``values``/``deltas``/
``ranking``/``overall_ranking`` keep their existing meaning. The uncertainty
information is strictly additive.
"""

from __future__ import annotations

import html as _html
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ._formatting import _fmt
from .campaign import pass_counts
from .core.types import RunResult
from .langfuse_client import LangfuseClient

logger = logging.getLogger(__name__)


class RankVerdict(StrEnum):
    """How much of an ordering the evidence actually supports.

    Deliberately mirrors :class:`eval_harness.campaign.Decision`'s vocabulary and
    semantics (``no_difference``/``cant_tell`` are the same strings meaning the
    same thing) rather than inventing a competing set. ``Decision`` names a
    *winning arm* and so cannot generalise to N models; this enum names the
    *shape of the claim* instead.
    """

    RANKED = "ranked"  # powered, and at least one strict separation is supportable
    NO_DIFFERENCE = "no_difference"  # powered, but every CI overlaps -> no ordering
    CANT_TELL = "cant_tell"  # below the power floor -> no claim
    NO_INTERVAL = "no_interval"  # statistic admits no sound interval (e.g. ``mean``)


@dataclass(frozen=True)
class RankConfidenceConfig:
    """Power floor + interval width for confidence-aware ranking.

    A ``*Config`` dataclass rather than literals at the call site (AGENTS.md).
    Both defaults mirror ``ABCampaignConfig`` (F-025) so the two features share
    one honesty convention:

    ``min_sample``
        Minimum scored items a model needs before any claim is made about it.
        Below it the verdict is ``cant_tell``. Default ``30``.
    ``wilson_z``
        Standard-normal multiplier for the Wilson interval. Default ``1.96``
        (~95%).
    """

    min_sample: int = 30
    wilson_z: float = 1.96


@dataclass
class ModelStats:
    """Per-model evidence behind one metric — the F-024 analogue of ``ArmStats``.

    ``successes``/``ci_low``/``ci_high`` are ``None`` when the metric is not a
    proportion, and ``interval`` records which is the case ("wilson" or "none").
    """

    model: str
    value: float | None
    successes: int | None
    n: int
    ci_low: float | None
    ci_high: float | None
    interval: str  # "wilson" | "none"

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "successes": self.successes,
            "n": self.n,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "interval": self.interval,
        }


@dataclass
class MetricComparison:
    """Per-score comparison across models — the shared primitive (also used by F-025)."""

    score: str
    metric: str  # "mean" | "pass_rate"
    values: dict[str, float | None]  # model name -> metric value (None if absent)
    deltas: dict[str, float | None]  # model name -> value - baseline value (None if undefined)
    ranking: list[str]  # model names, best (highest value) first; None values last
    # --- additive uncertainty information (never changes the four fields above) ---
    stats: dict[str, ModelStats] = field(default_factory=dict)
    verdict: RankVerdict = RankVerdict.CANT_TELL  # no-claim is the honest default
    confident_ranking: list[list[str]] = field(default_factory=list)  # tiers, best first
    min_sample: int = 0

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "metric": self.metric,
            "values": self.values,
            "deltas": self.deltas,
            "ranking": self.ranking,
            "verdict": self.verdict.value,
            "confident_ranking": self.confident_ranking,
            "min_sample": self.min_sample,
            "stats": {name: s.to_dict() for name, s in self.stats.items()},
        }


@dataclass
class ComparisonResult:
    runs: list[tuple[str, RunResult]]  # (model name, run result), in config order
    comparisons: list[MetricComparison]  # one per score, sorted by score name
    rank_by: str | None
    rank_metric: str
    overall_ranking: list[str]  # by rank_by score (or first score), best first
    # Additive: the same ordering, but only as far as the evidence supports it.
    overall_verdict: RankVerdict = RankVerdict.CANT_TELL
    overall_confident_ranking: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rank_by": self.rank_by,
            "rank_metric": self.rank_metric,
            "overall_ranking": self.overall_ranking,
            "overall_verdict": self.overall_verdict.value,
            "overall_confident_ranking": self.overall_confident_ranking,
            "models": [name for name, _ in self.runs],
            "runs": {name: result.to_dict() for name, result in self.runs},
            "comparisons": [c.to_dict() for c in self.comparisons],
        }

    def to_html(self, title: str = "Model comparison") -> str:
        return _render_html(self, title)


def _metric_value(result: RunResult, score: str, metric: str) -> float | None:
    agg = result.aggregate.get(score)
    if agg is None:
        return None
    return agg.mean if metric == "mean" else agg.pass_rate


def _model_stats(
    runs: list[tuple[str, RunResult]],
    score: str,
    metric: str,
    wilson_z: float,
) -> dict[str, ModelStats]:
    """Per-model evidence for ``score``.

    Only ``pass_rate`` is a proportion, so only it gets a Wilson interval; a
    ``mean`` gets its sample size and an explicit "no interval" marker.
    """
    if metric != "pass_rate":
        return {
            name: ModelStats(
                model=name,
                value=_metric_value(r, score, metric),
                successes=None,
                n=(r.aggregate[score].count if score in r.aggregate else 0),
                ci_low=None,
                ci_high=None,
                interval="none",
            )
            for name, r in runs
        }

    # Lazy, like campaign._arm_stats: agent-core is an optional sibling package.
    from agent_core.calibration import wilson_interval

    stats: dict[str, ModelStats] = {}
    for name, r in runs:
        successes, n = pass_counts(r, score)
        low, high = wilson_interval(successes, n, wilson_z)
        stats[name] = ModelStats(
            model=name,
            value=_metric_value(r, score, metric),
            successes=successes,
            n=n,
            ci_low=low,
            ci_high=high,
            interval="wilson",
        )
    return stats


def _tiers(bounds: list[tuple[str, float, float]]) -> list[list[str]]:
    """Split models (already best-first by point estimate) into evidence tiers.

    A tier boundary is opened only where the *whole* upper group strictly beats
    *everything* below it — ``min(ci_low above) > max(ci_high below)`` — so the
    claim "every model in this tier beats every model in the next" is defensible
    pairwise, not just between neighbours. Models whose intervals overlap stay in
    one tier and are therefore left unordered.
    """
    tiers: list[list[str]] = []
    start = 0
    for i in range(len(bounds) - 1):
        tier_low = min(low for _, low, _ in bounds[start : i + 1])
        rest_high = max(high for _, _, high in bounds[i + 1 :])
        if tier_low > rest_high:
            tiers.append([name for name, _, _ in bounds[start : i + 1]])
            start = i + 1
    tiers.append([name for name, _, _ in bounds[start:]])
    return tiers


def _rank_confidently(
    ranking: list[str],
    stats: dict[str, ModelStats],
    metric: str,
    min_sample: int,
) -> tuple[RankVerdict, list[list[str]]]:
    """Turn a point-estimate ranking into the ordering the evidence supports."""
    if metric != "pass_rate":
        # A proportion interval is invalid for an arbitrary-range mean; say so.
        return RankVerdict.NO_INTERVAL, []

    ordered = [stats[name] for name in ranking if stats[name].value is not None]
    if not ordered:
        return RankVerdict.CANT_TELL, []
    if any(s.n < min_sample for s in ordered):
        return RankVerdict.CANT_TELL, []

    bounds = [(s.model, s.ci_low, s.ci_high) for s in ordered if s.ci_low is not None and s.ci_high is not None]
    if len(bounds) != len(ordered):  # defensive: no interval => no ordering claim
        return RankVerdict.NO_INTERVAL, []

    tiers = _tiers(bounds)
    return (RankVerdict.RANKED if len(tiers) > 1 else RankVerdict.NO_DIFFERENCE), tiers


def compare_metric(
    runs: list[tuple[str, RunResult]],
    score: str,
    metric: str,
    baseline: str | None = None,
    *,
    confidence: RankConfidenceConfig | None = None,
) -> MetricComparison:
    """Compare one score across models: values, deltas vs baseline, and two rankings.

    Pure and reusable. ``None`` values (a score a model didn't emit, or a
    ``pass_rate`` of ``None``) are preserved and ranked last so the comparison
    never silently invents a number.

    ``ranking`` is the historical point-estimate order and is unchanged.
    ``confident_ranking`` is the additive, honest one: a list of tiers, best
    first, that refuses to order models whose confidence intervals overlap, and
    is empty whenever ``verdict`` is not ``ranked``/``no_difference``.
    ``confidence`` carries the power floor and interval width; callers inject it
    (``run_comparison`` derives it from the comparison config) rather than any
    numeric literal appearing here.
    """
    conf = confidence if confidence is not None else RankConfidenceConfig()
    values: dict[str, float | None] = {name: _metric_value(r, score, metric) for name, r in runs}

    base_val = values.get(baseline) if baseline is not None else None
    deltas: dict[str, float | None] = {}
    for name, val in values.items():
        deltas[name] = (val - base_val) if (val is not None and base_val is not None) else None

    # Rank by value descending; None last. Stable within ties / Nones (config order):
    # sorted() is itself stable, so the key must encode "descending" directly rather
    # than sorting ascending and reversing the whole list afterward -- a trailing
    # [::-1] flips the RESULT's order wholesale, which also swaps two tied models'
    # relative order even though neither one's key differs. Negating the numeric
    # part of the key gives descending-by-value while leaving equal keys, and
    # therefore config order, untouched.
    present = sorted((n for n in values if values[n] is not None), key=lambda n: -values[n])  # type: ignore[operator]
    absent = [n for n in values if values[n] is None]
    ordered = present + absent

    stats = _model_stats(runs, score, metric, conf.wilson_z)
    verdict, tiers = _rank_confidently(present, stats, metric, conf.min_sample)
    logger.debug(
        "compare_metric score=%s metric=%s verdict=%s ranking=%s confident=%s min_sample=%d",
        score,
        metric,
        verdict.value,
        ordered,
        tiers,
        conf.min_sample,
    )
    return MetricComparison(
        score=score,
        metric=metric,
        values=values,
        deltas=deltas,
        ranking=ordered,
        stats=stats,
        verdict=verdict,
        confident_ranking=tiers,
        min_sample=conf.min_sample,
    )


def _score_names(runs: list[tuple[str, RunResult]]) -> list[str]:
    names: set[str] = set()
    for _, r in runs:
        names.update(r.aggregate.keys())
    return sorted(names)


def _resolve_confidence(comp: Any, override: RankConfidenceConfig | None) -> RankConfidenceConfig:
    """Power floor / z for this comparison: explicit argument, else the config.

    ``ComparisonConfig`` declares ``min_sample``/``wilson_z``, so a YAML config
    sets them. They are read by *attribute* rather than by importing that model:
    this accepts any config-like object, which is what lets the pure ranking
    functions be unit-tested without building a whole ``EvalConfig``, and it
    keeps a hand-built comparison working. No literal appears at the call site
    either way -- the defaults live on ``RankConfidenceConfig``.
    """
    if override is not None:
        return override
    defaults = RankConfidenceConfig()
    return RankConfidenceConfig(
        min_sample=getattr(comp, "min_sample", defaults.min_sample),
        wilson_z=getattr(comp, "wilson_z", defaults.wilson_z),
    )


def run_comparison(
    config: Any,
    comparison: Any | None = None,
    *,
    langfuse_client: LangfuseClient | None = None,
    confidence: RankConfidenceConfig | None = None,
) -> ComparisonResult:
    """Run each model in ``comparison`` over ``config`` and compare the results.

    Each model reuses the base config with only its ``target`` (and the run name)
    swapped, so dataset/scorers/judge/gate behaviour is identical across models.
    """
    from .engine import EvalEngine

    comp = comparison if comparison is not None else getattr(config, "comparison", None)
    if comp is None:
        raise ValueError("run_comparison requires a comparison config (config.comparison or arg)")
    conf = _resolve_confidence(comp, confidence)

    runs: list[tuple[str, RunResult]] = []
    for model in comp.models:
        per_run = config.run.model_copy(update={"name": f"{config.run.name}::{model.name}", "run_id": None})
        per_model = config.model_copy(update={"target": model.target, "run": per_run, "comparison": None})
        engine = EvalEngine.from_config(per_model, langfuse_client=langfuse_client)
        runs.append((model.name, engine.run()))

    scores = _score_names(runs)
    comparisons = [compare_metric(runs, s, comp.rank_metric, comp.baseline, confidence=conf) for s in scores]

    rank_by = comp.rank_by if comp.rank_by is not None else (scores[0] if scores else None)
    overall_ranking: list[str] = []
    overall_verdict = RankVerdict.CANT_TELL
    overall_tiers: list[list[str]] = []
    for c in comparisons:
        if c.score == rank_by:
            overall_ranking = c.ranking
            overall_verdict = c.verdict
            overall_tiers = c.confident_ranking
            break

    logger.info(
        "comparison of %d model(s) ranked by %s (%s): verdict=%s point_ranking=%s confident_ranking=%s",
        len(runs),
        rank_by,
        comp.rank_metric,
        overall_verdict.value,
        overall_ranking,
        overall_tiers,
    )
    return ComparisonResult(
        runs=runs,
        comparisons=comparisons,
        rank_by=rank_by,
        rank_metric=comp.rank_metric,
        overall_ranking=overall_ranking,
        overall_verdict=overall_verdict,
        overall_confident_ranking=overall_tiers,
    )


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{_fmt(value)}"


def _fmt_ci(stats: ModelStats | None) -> str:
    if stats is None or stats.ci_low is None or stats.ci_high is None:
        return "n/a"
    return f"[{_fmt(stats.ci_low)}, {_fmt(stats.ci_high)}]"


_VERDICT_NOTE = {
    RankVerdict.RANKED: "intervals separate — the tiers below are supported by the evidence",
    RankVerdict.NO_DIFFERENCE: "powered, but every interval overlaps — no ordering claimed",
    RankVerdict.CANT_TELL: "below the power floor — no ordering claimed",
    RankVerdict.NO_INTERVAL: "no sound interval for this statistic — no ordering claimed",
}


def _fmt_tiers(tiers: list[list[str]]) -> str:
    """Tiers best-first; models inside a tier are unordered, so they are joined by ", "."""
    if not tiers:
        return "n/a"
    return " &gt; ".join(", ".join(_html.escape(name) for name in tier) for tier in tiers)


def _render_html(result: ComparisonResult, title: str) -> str:
    """Self-contained, deterministic HTML report (no external assets)."""
    esc = _html.escape
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{esc(title)}</title>",
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;}"
        "table{border-collapse:collapse;margin:1rem 0;}"
        "th,td{border:1px solid #ccc;padding:.3rem .6rem;text-align:left;}"
        "caption{font-weight:bold;text-align:left;margin-bottom:.3rem;}"
        ".note{color:#555;font-size:.9em;}</style>",
        "</head><body>",
        f"<h1>{esc(title)}</h1>",
        # NB: " &gt; " is already an HTML entity — escaping the joined string again
        # would render a literal "&gt;", so only the model names are escaped.
        f"<p>Ranked by <code>{esc(str(result.rank_by))}</code> "
        f"({esc(result.rank_metric)}): {' &gt; '.join(esc(n) for n in result.overall_ranking)}</p>",
        f"<p>Supported by the evidence: <strong>{esc(result.overall_verdict.value)}</strong> — "
        f"{esc(_VERDICT_NOTE[result.overall_verdict])}. "
        f"Confident ranking: {_fmt_tiers(result.overall_confident_ranking)}</p>",
    ]
    for c in result.comparisons:
        parts.append(f"<table><caption>{esc(c.score)} ({esc(c.metric)})</caption>")
        parts.append("<tr><th>model</th><th>value</th><th>delta</th><th>n</th><th>CI</th></tr>")
        for name in c.ranking:
            st = c.stats.get(name)
            parts.append(
                f"<tr><td>{esc(name)}</td><td>{_fmt(c.values[name])}</td>"
                f"<td>{_fmt_delta(c.deltas[name])}</td>"
                f"<td>{st.n if st is not None else 'n/a'}</td><td>{_fmt_ci(st)}</td></tr>"
            )
        parts.append("</table>")
        parts.append(
            f'<p class="note">verdict: <strong>{esc(c.verdict.value)}</strong> '
            f"({esc(_VERDICT_NOTE[c.verdict])}; min_sample={c.min_sample}) — "
            f"confident ranking: {_fmt_tiers(c.confident_ranking)}</p>"
        )
    parts.append("</body></html>")
    return "\n".join(parts)

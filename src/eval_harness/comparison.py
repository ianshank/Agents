"""Multi-model comparison (F-024).

Runs the same dataset/scorers/judge against several targets and produces a
comparative result: per-metric values, deltas vs a baseline, and a ranking.

Reuses the existing machinery rather than duplicating it: each model is a normal
single-target run through :class:`~eval_harness.engine.EvalEngine`, so all
scoring/aggregation/parallelism behaviour is identical to a one-model run. The
small :func:`compare_metric` primitive (per-metric values + deltas + ranking) is
shared with the A/B campaign feature (F-025).

Backwards compatible: this is an additive, opt-in entry point; the single-run
path is untouched and ``SCHEMA_VERSION`` is unchanged.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass

from ._formatting import _fmt
from .config.models import ComparisonConfig, EvalConfig
from .core.types import RunResult
from .langfuse_client import LangfuseClient


@dataclass
class MetricComparison:
    """Per-score comparison across models — the shared primitive (also used by F-025)."""

    score: str
    metric: str  # "mean" | "pass_rate"
    values: dict[str, float | None]  # model name -> metric value (None if absent)
    deltas: dict[str, float | None]  # model name -> value - baseline value (None if undefined)
    ranking: list[str]  # model names, best (highest value) first; None values last

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "metric": self.metric,
            "values": self.values,
            "deltas": self.deltas,
            "ranking": self.ranking,
        }


@dataclass
class ComparisonResult:
    runs: list[tuple[str, RunResult]]  # (model name, run result), in config order
    comparisons: list[MetricComparison]  # one per score, sorted by score name
    rank_by: str | None
    rank_metric: str
    overall_ranking: list[str]  # by rank_by score (or first score), best first

    def to_dict(self) -> dict:
        return {
            "rank_by": self.rank_by,
            "rank_metric": self.rank_metric,
            "overall_ranking": self.overall_ranking,
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


def compare_metric(
    runs: list[tuple[str, RunResult]],
    score: str,
    metric: str,
    baseline: str | None = None,
) -> MetricComparison:
    """Compare one score across models: collect values, deltas vs baseline, ranking.

    Pure and reusable. ``None`` values (a score a model didn't emit, or a
    ``pass_rate`` of ``None``) are preserved and ranked last so the comparison
    never silently invents a number.
    """
    values: dict[str, float | None] = {name: _metric_value(r, score, metric) for name, r in runs}

    base_val = values.get(baseline) if baseline is not None else None
    deltas: dict[str, float | None] = {}
    for name, val in values.items():
        deltas[name] = (val - base_val) if (val is not None and base_val is not None) else None

    # Rank by value descending; None last. Stable within ties / Nones (config order).
    ranking = sorted(values, key=lambda n: (values[n] is not None, values[n] if values[n] is not None else 0.0))
    # sorted() above is ascending on (has_value, value); reverse for best-first but
    # keep None entries (has_value False) at the end.
    present = [n for n in ranking if values[n] is not None][::-1]
    absent = [n for n in ranking if values[n] is None]
    return MetricComparison(score=score, metric=metric, values=values, deltas=deltas, ranking=present + absent)


def _score_names(runs: list[tuple[str, RunResult]]) -> list[str]:
    names: set[str] = set()
    for _, r in runs:
        names.update(r.aggregate.keys())
    return sorted(names)


def run_comparison(
    config: EvalConfig,
    comparison: ComparisonConfig | None = None,
    *,
    langfuse_client: LangfuseClient | None = None,
) -> ComparisonResult:
    """Run each model in ``comparison`` over ``config`` and compare the results.

    Each model reuses the base config with only its ``target`` (and the run name)
    swapped, so dataset/scorers/judge/gate behaviour is identical across models.
    """
    from .engine import EvalEngine

    comp = comparison if comparison is not None else config.comparison
    if comp is None:
        raise ValueError("run_comparison requires a comparison config (config.comparison or arg)")

    runs: list[tuple[str, RunResult]] = []
    for model in comp.models:
        per_run = config.run.model_copy(update={"name": f"{config.run.name}::{model.name}", "run_id": None})
        per_model = config.model_copy(update={"target": model.target, "run": per_run, "comparison": None})
        engine = EvalEngine.from_config(per_model, langfuse_client=langfuse_client)
        runs.append((model.name, engine.run()))

    scores = _score_names(runs)
    comparisons = [compare_metric(runs, s, comp.rank_metric, comp.baseline) for s in scores]

    rank_by = comp.rank_by if comp.rank_by is not None else (scores[0] if scores else None)
    overall_ranking: list[str] = []
    for c in comparisons:
        if c.score == rank_by:
            overall_ranking = c.ranking
            break

    return ComparisonResult(
        runs=runs,
        comparisons=comparisons,
        rank_by=rank_by,
        rank_metric=comp.rank_metric,
        overall_ranking=overall_ranking,
    )


def _fmt_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{_fmt(value)}"


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
        "caption{font-weight:bold;text-align:left;margin-bottom:.3rem;}</style>",
        "</head><body>",
        f"<h1>{esc(title)}</h1>",
        f"<p>Ranked by <code>{esc(str(result.rank_by))}</code> "
        f"({esc(result.rank_metric)}): {esc(' &gt; '.join(result.overall_ranking))}</p>",
    ]
    for c in result.comparisons:
        parts.append(f"<table><caption>{esc(c.score)} ({esc(c.metric)})</caption>")
        parts.append("<tr><th>model</th><th>value</th><th>delta</th></tr>")
        for name in c.ranking:
            parts.append(
                f"<tr><td>{esc(name)}</td><td>{_fmt(c.values[name])}</td><td>{_fmt_delta(c.deltas[name])}</td></tr>"
            )
        parts.append("</table>")
    parts.append("</body></html>")
    return "\n".join(parts)

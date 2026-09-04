# 0041 — Confidence-aware multi-model comparison (additive)

- Status: **Accepted.** Additive and backwards compatible; `SCHEMA_VERSION` is unchanged.
- Date: 2026-09-04
- Related: ADR 0011 (multi-model comparison, F-024), ADR 0012 (A/B campaigns, F-025),
  ADR 0006 (behavioral-regression honesty), `src/eval_harness/comparison.py`,
  `src/eval_harness/campaign.py`, `agent_core.calibration.wilson_interval`.

## Context

The repo held two features to two different standards of evidence.

`campaign.py` (F-025) decides A/B significance from Wilson intervals, enforces a
`min_sample` power floor, and returns an explicit `cant_tell` rather than claiming a
difference it cannot support.

`comparison.py` (F-024) ranked models on **raw point estimates**: collect `mean`/`pass_rate`,
subtract a baseline, sort, publish a winner. No interval, no sample size, no power floor, no
abstention. On a 50-item dataset a 2-point pass-rate difference is noise, but `to_dict()` and
the HTML report presented it as an ordering.

This mattered more after the recently fixed defect where items whose target raised were
silently dropped from a run, inflating its `pass_rate`: the model with the most infrastructure
failures could win the comparison outright.

## Decision

Bring F-024 up to F-025's standard **additively**, reusing F-025's machinery and vocabulary.

1. **Reuse, never reimplement.** `agent_core.calibration.wilson_interval` supplies the
   per-model interval, over the permitted `eval_harness -> agent_core` edge. It is imported
   **lazily inside the function**, exactly as `campaign._arm_stats` does, because `agent-core`
   is not a runtime dependency of `langfuse-eval-harness` (`pyproject.toml` declares only
   `pyyaml` and `pydantic`): importing `comparison` and running the whole point-estimate path
   must keep working when the sibling package is absent. `campaign.pass_counts` supplies the
   `(successes, n)` pair so the interval's denominator matches `pass_rate` semantics exactly.
   `ScoreAggregate.count` is deliberately *not* used as `n` — it counts scores whose `passed`
   is `None`, and would silently widen the denominator.

2. **A verdict, not just an order.** `RankVerdict` mirrors `campaign.Decision`'s vocabulary
   and semantics — `no_difference` and `cant_tell` are the same strings meaning the same
   thing. `Decision` names a *winning arm* and cannot generalise to N models, so the new enum
   names the *shape of the claim* instead: `ranked` (a separation is supportable),
   `no_difference` (powered, every interval overlaps), `cant_tell` (below the power floor),
   `no_interval` (the statistic admits no sound interval — see 4).

3. **Tiers, not a total order.** `confident_ranking` is a list of tiers, best first. A tier
   boundary is opened only where `min(ci_low)` over the whole upper group exceeds
   `max(ci_high)` over *everything* below it, so "each model in this tier beats each model in
   the next" is defensible pairwise rather than only between neighbours. Models whose
   intervals overlap stay in one tier and are left unordered; models with no value at all
   (`None`) are excluded from the claim entirely rather than being invented into it.

4. **`mean` gets no binomial interval.** `pass_rate` is a proportion, so Wilson applies
   directly. `mean` is an arbitrary-range average; a proportion interval is invalid for it and
   agent_core offers no sound alternative today. Rather than inventing one, the verdict is
   `no_interval`, the point-estimate ranking is still reported, and the report says so in
   words — the same honesty as `cant_tell`. A future mean interval (bootstrap or t) is a
   separate decision and belongs in `agent_core`, not here.

5. **The power floor is configuration.** `RankConfidenceConfig` (`min_sample=30`,
   `wilson_z=1.96`, both defaults documented on the field and both mirroring
   `ABCampaignConfig`) replaces literals at the call site, per AGENTS.md. `run_comparison`
   takes an optional `confidence=` injection and otherwise reads `min_sample`/`wilson_z` off
   the comparison config by attribute, so it works today and picks the values up automatically
   once `ComparisonConfig` grows those two fields (see Consequences).

## Consequences

- **Backwards compatible.** `MetricComparison.values`/`deltas`/`ranking` and every existing
  `to_dict()` key keep their meaning; `stats`, `verdict`, `confident_ranking`, `min_sample`,
  `overall_verdict` and `overall_confident_ranking` are strictly additive, and the new
  dataclass fields all carry defaults so positional construction still works.
  `SCHEMA_VERSION` is untouched.
- **Conservative by construction.** The no-claim verdict is the *default* value of
  `MetricComparison.verdict`, so a comparison built without evidence claims nothing.
- **The default path claims nothing yet.** `ComparisonConfig.rank_metric` defaults to `mean`,
  which yields `no_interval`. That is the honest answer, and it makes the `pass_rate` opt-in
  the path that carries a defensible ordering.
- **Config fields still owed.** `ComparisonConfig` should gain `min_sample: int = Field(30,
  ge=1)` and `wilson_z: float = Field(1.96, gt=0)`, mirroring `ABCampaignConfig`. They were
  not added in this change because `config/models.py` was being edited concurrently; the
  attribute-read in `_resolve_confidence` is forward compatible with them.
- **Report fix.** `_render_html` gained `n` and CI columns plus per-metric and overall verdict
  lines, and a real double-escaping bug was fixed: `esc(" &gt; ".join(...))` turned the
  already-entity separator into `&amp;gt;`, which browsers rendered as a literal `&gt;`.
- **Tested offline.** `tests/test_comparison_confidence.py` — deterministic hand-built
  `RunResult` fixtures for the interval maths plus the existing `echo` targets end to end. No
  clock, RNG, network or filesystem.

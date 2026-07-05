# Gap Analysis — behavioral-regression

An honest account of what this package is, what it deliberately is not, and the residual
limitations of what it builds. Mirrors `agent-core/GAP_ANALYSIS.md` so every package in the
monorepo carries the same candour surface.

## 1. Built to production quality

The 7-beat pipeline (generator → contested judge → κ/power validation → detector → canary →
ship/hold/escalate gate → report) is real, tested logic — not scaffolding. Measured baseline
(2026-07): **100% branch coverage** against a ≥95% gate, strict mypy, ruff clean, across
Python 3.10–3.12. A run is byte-reproducible from `(BRConfig, seed)`. Structured logging with
`debug_span` instruments the gate, canary, detector, and pipeline. Every threshold lives on the
frozen `BRConfig`; decision logic never embeds a literal, and configs are versioned with a
migration chain for backwards compatibility.

## 2. Reuse, not reinvention

The statistics are reused from the monorepo's proven primitives, never re-derived: Wilson CI /
reliability bins / Brier from `agent_core.calibration`, bootstrap delta CI from
`flow_corpus.validation.resampling`, oracle-κ + power gate from `flow_corpus.oracles.kappa_gate`,
and the ship/hold/escalate layering from `agent_core.merge_gate`. The dependency direction is
acyclic and enforced by the grimp drift gate: `behavioral_regression → flow_corpus →
{flow_protocol, agent_core}`. This package never imports `eval_harness` (the airgap).

## 3. Deliberate design choices (not gaps)

- **Synthetic, deliberately-imperfect judge.** The default `SyntheticJudge` is offline and
  intentionally fallible — the point is to *measure* the judge (κ vs human labels, power) before
  trusting it, not to ship a perfect one. The live `AnthropicJudge` is wired in only by the
  harness layer, outside the airgap.
- **Fail-safe-to-escalate.** When the measurement cannot support a confident call, the gate
  returns ESCALATE, never a false SHIP. The `"can't tell"` bucket is a first-class outcome.
- **Offline/deterministic default.** No network or live model on the default path, by design, so
  results are reproducible and CI-safe.

## 4. Known limitations of what IS built

- The default signal is **synthetic**: it exercises the *statistical* machinery end-to-end, not a
  real model's behaviour. Real-model conclusions require the live judge path (harness layer) and
  real transcripts.
- Judge calibration (κ, power) is validated **in-sample** within the test fixtures; out-of-sample
  drift of a live judge is not modelled here.
- The optional Streamlit `dashboard.py` and the `__main__`/CLI entrypoints are exercised via
  subprocess/manual use and are **omitted from the coverage source set** (they need the optional
  `dashboard` extra); the gated logic underneath them is fully covered.

## 5. Coverage residual

Actual coverage exceeds the 95% gate (100% at the 2026-07 baseline). The only source excluded
from measurement is the dashboard/CLI surface noted above, per the package `pyproject.toml`
`omit` list — a documented seam, not padding.

## 6. Cross-reference

The repository-level measured baseline behind these numbers is recorded in
`docs/gap-analysis-2026-07.md`; the structural-budget enforcement that now guards this package
(complexity < 15, file ≤ 500 lines) is ADR 0019.

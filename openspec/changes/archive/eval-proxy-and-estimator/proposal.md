# Change: eval-proxy-and-estimator

**Status:** landed — F-047 @ `5404912bdb` · **Date:** 2026-07-25 · **Author track:** `claude/` agent lane
**Motivated by:** `./review.md` (peer review of the "swap Wilson → PPI++" critique)
**Compiles down to:** `docs/plans/<topic>/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

The merge-gate calibration path reports plain Wilson intervals and the audit sampler stores
no selection propensity. An external critique proposed replacing Wilson with PPI++. The peer
review (`./review.md`) verified the statistics but found the critique wrong on magnitude and
mechanism: the gate's real activation bar is a **four-gate Wilson stack** needing ~380
near-perfect audits per domain, and PPI++ on the calibrated-confidence proxy buys only
~1.05–1.1× effective-N — near-zero on the *conditional* subsets the gate operates on. The
gain, if any, is governed entirely by **which proxy** is used and its **conditional**
correlation with human-audit correctness. That correlation is unmeasured and computable
today. This change measures it, makes the audit sampler PPI-ready, and adds an honest
dual-estimator to the report — without touching the gate.

## What changes

- **WS-A (centerpiece):** a read-only `proxy_eval` that computes marginal and **conditional**
  `ρ(proxy, HUMAN_AUDIT)` and the implied PPI effective-N multiplier `1/(1−ρ²)` for candidate
  proxies (calibrated confidence; passive REVERT/CI/timeout labels; optional LLM-judge
  score), emitted as a dated `docs/calibration-proxy-correlation-*.md` snapshot.
- **WS-B:** add a nullable `selection_propensity` field to `OutcomeRecord` and populate it in
  the audit sampler (the known `k/N + (1−k/N)·base_rate` inclusion probability), enabling
  future Horvitz–Thompson / PPI weighting.
- **WS-C:** add a power-tuned `ppi_plus_interval` to `agent_core.calibration` and a
  `--estimator {wilson, ppi++}` dual-report to `calibration_report`, scoped to the
  aggregate/base-rate estimates. Wilson stays the gate estimator.

## Scope / non-goals

- **Non-goal: any gate change.** `merge_gate.decide()`, `tau`, `min_calibration_n`,
  `wilson_floor`, and the ADR 0005 enablement checklist are untouched. Auto-merge stays off.
- **Non-goal (this change): `risk_target` / `wilson_floor` tuning.** That is a separate
  **risk-appetite ADR** (a policy lever, not estimator work) — filed as a follow-on.
- **Deferred:** multi-task PPI, active/robust sampling, stratified PPI, judge-noise-aware
  intervals, cross-cell shrinkage — none pays off until ≥3 populated `(agent_version, domain)`
  cells and a measured ρ exist (`./review.md` §5).

## Impact

- New F-IDs (claimed at land) for WS-A, WS-B, WS-C with `scripts/validations/F_0NN.py` proofs.
- Source: new `agent-core/agent_core/proxy_eval.py`; edits to `outcome_store.py`,
  `audit_sampler.py`, `calibration.py`, `calibration_report.py` (all non-protected).
- Protected step (isolated PR, `eval-change-approved`): propensity emission in
  `.github/workflows/merge-gate-audit.yml`; the F-IDs and validations.
- New docs snapshot; CHANGELOG entry (user-visible report flag).

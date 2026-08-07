# 0026 — Proxy-correlation measurement, the PPI++ report estimator, and audit-selection propensity

- Status: **Accepted.**
- Date: 2026-07-25
- Related: [0005](0005-calibrated-merge-gate.md), [0018](0018-outcome-store-persistence.md),
  [0023](0023-agent-confidence-proxy-and-agent-domain-seeding.md),
  [0025](0025-outcome-record-forward-compatibility.md); F-043, F-034, F-047;
  `openspec/changes/archive/eval-proxy-and-estimator/` (peer review, design, tasks).

## Context

An external critique proposed replacing the merge gate's Wilson interval with **PPI++**,
arguing the soak-scale sample cannot support a CI-lower-bound gate. A peer review
(committed at `openspec/changes/archive/eval-proxy-and-estimator/review.md`) verified the
arithmetic and the citations and found the *direction* right but the *targeting* wrong:

- The critique attacks an `N>=20` **soak counter**, not a decision gate. The operative bar
  is a **four-gate Wilson stack**, the worst of which (`threshold_for_risk` at
  `risk_target=0.02`, on a held-out fold) needs roughly **380 near-perfect audited records
  per domain** before `tau` can exist at all.
- PPI++ on the calibrated-confidence proxy buys only ~1.05–1.1× effective-N at the
  system's own `min_auroc=0.65` floor, and structurally ~0 on the *conditional* subsets the
  gate operates over: `E[correct | score >= tau]` and `E[correct | bin]` restrict the range
  of a confidence-like proxy by construction, so its within-subset correlation collapses.
- The lever is therefore **which proxy is used**, not which estimator. Measured on a
  synthetic soak (400 merges / 23 audits): Wilson half-width 0.1508, PPI++ on
  `raw_confidence` 0.1402 (1.08×), PPI++ on the orthogonal `passive_label` 0.0925 (1.63×).

Separately, the audit sampler's per-domain floor deliberately over-samples low-volume
domains. Correcting that needs each record's inclusion probability — a quantity that
**cannot be reconstructed after the round**.

## Decision

### 1. Measure the proxy before trusting any estimator

`agent_core.proxy_eval` reports proxy↔`HUMAN_AUDIT` correlation **marginally and
conditionally** (on `score >= candidate tau` and per bin), with the implied
`1/(1-rho^2)` effective-sample multiplier. The difference between the marginal and
conditional rows *is* the finding; a report that showed only the marginal number would
recommend the wrong lever.

Proxies are pluggable via a `ProxyExtractor` Protocol (`agent_core.proxies`). This is a
seam of the same kind as the harness's SDK-optional clients: an external LLM judge's
scores arrive through `MappingProxy` / `--judge-scores`, so `agent_core` gains no
dependency and stays pure stdlib.

### 2. PPI++ is a **report** estimator, fail-closed, and never the gate's

`calibration_report` gains `--estimator {wilson,ppi++}`. **Wilson remains the default and
the only estimator the gate uses** — `merge_gate.decide()` is unchanged, and neither
`merge_gate` nor `merge_gate_ci` imports the estimator or the report modules, so no new
code path can reach an auto-merge decision (pinned by `F_047.py`).

`ppi_plus_interval` returns the **Wilson** interval, with a stated reason, on every path
where the normal approximation cannot be trusted: too few labels, a single outcome class
(zero variance would collapse the interval to a false-certainty point), a constant proxy,
an out-of-contract proxy, or no residual degrees of freedom. `lambda = 0` reproduces the
classical estimator *exactly*, which is what makes "never asymptotically worse" true.

Two consequences are load-bearing and non-obvious:

- **`variance_reduction` is derived from the standard errors, never from the rendered
  bounds.** Those are clipped to `[0, 1]`, so a ratio of clipped widths measures proximity
  to a boundary rather than variance — it reported a 3% gain as 94%, non-monotonically.
- **A tuned `lambda` costs the residual a second degree of freedom** (it is fitted from the
  same points), so `min_labeled >= 3` and a runtime guard refuse the case where none
  remain. Without it a half-width of 0.06 was reachable from two observations.

The report also renders the same-family `lambda = 0` baseline the reduction is measured
against, and states that cross-domain aggregates are **unweighted** while no estimator
applies the `1/p` correction.

### 3. Record `selection_propensity` now, wired end to end

`OutcomeRecord` gains a nullable `selection_propensity`, and the audit chain carries it:
`merge-gate-audit` selects `--with-propensity`, `audit_issue_sync` surfaces it in the issue
and in the dispatch command, and `merge-gate-verdict` → `record_audit_verdict` threads it
to the write boundary.

Nullable and additive per **ADR 0025**: records written before the field load unchanged,
and both `selected.txt` line formats parse. **Unknown stays unknown** — inventing a value
would silently corrupt the very reweighting the field exists to enable.

Recorded now rather than when needed, because the probability is only knowable during the
round that produced it.

## Consequences

- **Positive.** The Phase-4 "does confidence discriminate?" question becomes answerable
  with a measured number instead of an argument. The estimator is available for the
  aggregate report without touching autonomy. The propensity is captured while it exists.
- **Negative / accepted.** One more estimator to explain; a report column that must be read
  as report-only. `agent_core` grew four modules — offset by the 500-line file budget,
  which the split satisfies.
- **Explicitly not decided here.** Changing `risk_target` or `wilson_floor` is a
  **risk-appetite** decision, not an estimator one, and belongs in its own ADR. Multi-task
  PPI, active/robust sampling, stratified PPI and cross-cell shrinkage stay deferred until
  ≥3 populated `(agent_version, domain)` cells and a measured `rho` exist.
- **Reversibility.** `proxy_eval` is read-only; `selection_propensity` is additive and
  nullable; `--estimator` defaults to `wilson`. Reverting is flag/field removal with no
  data migration.

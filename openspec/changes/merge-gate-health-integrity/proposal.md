# Change: merge-gate-health-integrity

**Status:** proposed · **Date:** 2026-07-31 · **Author track:** `claude/` agent lane
**Motivated by:** `./review.md` (independent re-verification of `docs/gap-analysis-merge-gate-2026-07-24.md`)
**Compiles down to:** an F-ID (claimed at land) + `scripts/validations/F_0NN.py` + a design ADR.

## Why

The calibrated merge gate trusts a domain's confidence only when its calibrator is *healthy*:
enough samples, low ECE, an AUROC that rank-orders correctness, and a tight confidence
interval in the region where auto-merges happen (ADR 0005 §5). Re-verifying the 2026-07-24
gap analysis against HEAD found that the fourth of those four floors could report a pass
having measured nothing at all — and that reaching `AUTO_MERGE` that way is reproducible
under stock configuration:

```
6600 HUMAN_AUDIT records, every raw_confidence in {0.05, 0.45}
  -> CalibratorHealth(n=6600, ece=0.0, auroc=1.0, bin_ci_width=0.0)
  -> is_trustworthy=True, tau=1.0
  -> decide(raw_confidence=0.45) == AUTO_MERGE
```

`_upper_half_ci_width` scanned only bins above raw 0.5, accumulating into a `0.0`
initialiser. A domain whose audits all sit below that left every scanned bin empty, so the
`max`-reduction returned its identity element and satisfied `max_bin_ci_width` vacuously.
The scan was also on the wrong axis: `decide()` gates on the *calibrated* `p` against `tau`,
so "the upper half of the raw score range" was neither where auto-merges happen nor
something that function could observe.

Alongside it, `GatePolicyConfig` — which holds every value governing autonomy — was the only
`agent_core` config without a `__post_init__` and had exactly one production construction, a
bare `GatePolicyConfig()`. It accepted `risk_target=1.0` (which collapses `tau` to the
smallest observed score, so every change clears the threshold) and could only be changed by
editing library source, even though ADR 0005 §3 promises a **human-set** `risk_target` and
calls tuning it "a human decision".

All of this is latent today: the live store holds 71 records and **zero** `HUMAN_AUDIT`
labels, so `build_domain_models` returns `{}` and every domain cold-starts to `ESCALATE`.
These defects activate precisely when the gate goes live — which is the argument for landing
the fix now, while it is provably decision-neutral, rather than after activation when it
would not be.

## What changes

- **WS-A (centerpiece):** replace `_upper_half_ci_width` with `_operating_bin_ci_width`,
  which measures the widest Wilson interval among bins that could plausibly be an operating
  point, and returns `None` when none can. Eligibility is defined by the per-decision Wilson
  floor — a bin whose Wilson *upper* bound cannot reach `wilson_floor` can never be an
  operating point whatever `tau` turns out to be — so the region is tau-free, computable at
  health time, and defined on the axis the decision is actually made on.
  `CalibratorHealth.bin_ci_width` becomes `float | None` and `is_trustworthy` rejects `None`.
- **WS-B:** give `GatePolicyConfig` a `__post_init__` bounding all nine tunables, and expose
  them as CLI flags on `merge_gate_ci` with an exit-2 (usage) path. `min_auroc` is bounded
  strictly above `0.5` so the single-class AUROC sentinel cannot pass the floor it is
  documented to fail.
- **WS-C:** single-source the bin count (`calibration.DEFAULT_N_BINS` +
  `GatePolicyConfig.n_bins`), threaded explicitly at every call site; and unify score→bin
  routing in `_bin_of` so `fit` and `bin_index` cannot disagree about where a score belongs.
- **WS-D:** floor `min_calibration_n` on the held-out fold that the other metrics are
  measured on, and pin the previously untested held-out contract with a mutation-resistant
  test.

## Scope / non-goals

- **Non-goal: enabling the gate.** Auto-merge stays default-off. The ADR 0005 enablement
  checklist is untouched and every change here is strictly fail-closed or decision-neutral.
- **Non-goal: workflow policy wiring.** `.github/workflows/calibrated-merge-gate.yml` is not
  wired to the new flags in this change: any repo variable actually set would alter live
  shadow decisions, turning a decision-neutral change into a decision-changing one. Filed as
  a follow-on, and it must use the bash-array idiom (`AGENTS.md`) when it lands.
- **Non-goal: `risk_target` / `wilson_floor` retuning.** This change creates the seam through
  which a human can tune them; choosing the values is a risk-appetite decision, not
  correctness work.
- **Deferred:** the remaining gap-analysis findings (G4/G5-residue observability, G6 typing,
  G7 duplicate `configure_logging`, G8 dead-line coverage, G9 CI coverage allowlist) — real
  but low-severity, and none of them can change a gate decision.

## Impact

- **New F-ID** claimed at land, with `scripts/validations/F_0NN.py` as its offline proof.
- **Source touched:** `agent-core/agent_core/{merge_gate,outcome_store,merge_gate_ci,calibration}.py`.
- **Tests touched:** `agent-core/tests/test_{outcome_store,merge_gate,merge_gate_ci,outcome_labeller}.py`
  — protected paths (`scripts/eval_protected_paths.py`), so the PR carries `eval-change-approved`.
- **Decision-changing when live** (all currently latent, declared in the CHANGELOG): the
  sample floor now counts held-out records; an unmeasurable region blocks a domain;
  out-of-contract scores move from the top bin to bin 0. All strictly fail-closed. The
  re-axis is looser in one direction — mediocre mid bins that inflate today's width but can
  never be operating points no longer block a domain.
- **Not touched:** `SCHEMA_VERSION`, `FrameworkConfig`, the `Calibrator` Protocol, and the
  gate's default-off posture.

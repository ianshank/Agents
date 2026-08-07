# 0029 - Calibrator health is measured on the operating region, and an unmeasurable floor never passes

**Status**: Accepted
**Date**: 2026-07-31

Related: [ADR 0005](0005-calibrated-merge-gate.md) (the gate this hardens),
[ADR 0025](0025-outcome-record-forward-compatibility.md) (why the store fails closed rather
than raising), `openspec/changes/archive/merge-gate-health-integrity/`,
`docs/gap-analysis-merge-gate-2026-07-24.md`.

## Context and Problem Statement

ADR 0005 §5 makes calibrator health a precondition for autonomy: "Auto-merge needs enough
samples, low ECE, an AUROC that rank-orders correctness, and a tight upper-bin CI". Three of
those four floors were enforced. The fourth could report a pass having measured nothing.

`_upper_half_ci_width` scanned the bins above raw confidence 0.5 and accumulated the widest
Wilson interval into `widest = 0.0`. When every scanned bin was empty the function returned
its initialiser — the identity element of a `max`-reduction over an empty set — and `0.0`
trivially satisfies `bin_ci_width <= max_bin_ci_width`. "No evidence" scored identically to
"strongest possible evidence".

This is reachable, not theoretical. Reproduced with stock `GatePolicyConfig()`:

```
6600 HUMAN_AUDIT records, every raw_confidence in {0.05, 0.45}
  -> CalibratorHealth(n=6600, ece=0.0, auroc=1.0, bin_ci_width=0.0)
  -> is_trustworthy=True, tau=1.0
  -> decide(raw_confidence=0.45) == AUTO_MERGE
```

A second, deeper defect made the first one possible. `decide()` compares the **calibrated**
`p` against `tau` (`merge_gate.py:165-166`), not the raw score. So "the upper half of the raw
score range" was never "the region where auto-merges actually happen", as the function's
docstring claimed — the reproduction above auto-merges at raw 0.45, in a region that scan
cannot inspect by construction. A domain whose entire audit history sits below 0.5 raw can
still calibrate to `p == 1.0`.

Two constraints ruled out the obvious fixes. `tau` cannot define the region, because `tau` is
derived *from* health and does not exist when health is computed. And the region cannot be
found by re-binning the calibrated values, because two distinct bins can share an accuracy and
pooling them produces an over-narrow interval — which is why the code binned by raw score in
the first place.

Separately, `GatePolicyConfig` — which holds every value governing autonomy — was the only
`agent_core` config without a `__post_init__`, and its sole production construction was a bare
`GatePolicyConfig()`. It accepted `risk_target=1.0`, which collapses `tau` to the smallest
observed score so that every change clears the threshold. ADR 0005 §3 promises a **human-set**
`risk_target` and calls tuning it "a human decision"; no seam existed through which a human
could make it.

## Decision

**1. The operating region is defined by the per-decision Wilson floor.** `decide()` can only
reach `AUTO_MERGE` when the operating bin satisfies
`wilson_lower(succ, n, z) >= wilson_floor`. Therefore a bin whose Wilson **upper** bound
cannot reach `wilson_floor` can never be an operating point, whatever `tau` turns out to be.
That predicate is tau-free, computable at health time, and defined on the calibrator's own
bins — the axis the decision is made on. Grouping stays by bin **index**, never by predicted
value, preserving the anti-conflation property.

**2. Unmeasurable is `None`, and `None` is untrustworthy.** `_operating_bin_ci_width` returns
`float | None`; `is_trustworthy` rejects `None`. NaN was rejected despite in-repo precedent:
it compares False against every bound, which is the one-sided fail-open this very subsystem
has already been bitten by twice (`ChangeContext.__post_init__`, `BinningCalibrator.bin_index`).
`inf` was rejected because it conflates "not measured" with "measured as maximally wide" —
the distinction being restored. `None` is verified by mypy strict at every use site.

**3. A sentinel alone was insufficient.** Returning `None` while keeping the raw-half scan
would fix the vacuous pass but leave the measurement on the wrong axis, turning the fail-open
into an arbitrary blocker keyed on the agent's confidence *scale*. Health would depend on how
an agent labels its confidence rather than on whether that confidence is trustworthy. Decision
1 subsumes the sentinel: `None` is its degenerate case.

**4. Policy bounds reject the vacuous endpoint and allow the strict one.** A floor that can
never reject is worse than no field, because the audit log then reports a check that did no
work; a floor that can never accept is a kill switch, which is safe. Hence
`risk_target ∈ [0, 1)`, `wilson_floor ∈ (0, 1]`, `max_ece ∈ [0, 1)`, `min_auroc ∈ (0.5, 1]`,
`min_calibration_n >= 1`, `n_bins >= 2`. `min_auroc`'s lower bound is load-bearing: the
single-class AUROC sentinel is `0.5`, and `build_domain_models` documents that it "fails the
health floor" — true only while this bound holds. No cross-field validation, because
`risk_target <= 1 - wilson_floor` would reject configurations strictly more conservative than
the defaults.

**5. `protected_auto_merge` is neither validated nor operator-reachable.** Rejecting `True`
would delete an escape hatch ADR 0005 documents and the suite exercises. Exposing a flag would
let a workflow disable the protected-path layer. It stays reachable in-process and logs a
warning when set.

**6. The sample floor counts the fold it measures.** `min_calibration_n` now floors the
held-out count; the both-fold total is retained as a non-gating diagnostic.

**7. The store fails closed; the metrics layer keeps raising.** `_bin_of` is the single
score→bin router. Out-of-contract scores floor to bin 0 at the store boundary and never raise,
because outcome records are deliberately load-tolerant (ADR 0025) and one malformed historical
line must not fail the gate on every change. `agent_core.calibration` keeps raising, correctly:
its inputs are computed rather than loaded.

## Consequences

- The fourth health floor does work. On the regression fixture the same input moves from `0.0`
  (vacuous pass) to `0.7935` (honest fail).
- `wilson_floor` now influences health. Lowering it — weakening the per-decision check —
  admits more bins into the region and so makes health *stricter*. The two knobs balance
  rather than compound. This is unintuitive and is stated here deliberately.
- Under honest measurement, `max_bin_ci_width = 0.20` may require roughly 50+ high-accuracy
  audits in **every** eligible bin, and could keep the gate permanently closed. That is the
  correct default per ADR 0005 ("the default is to escalate"), and the constraint becoming
  visible instead of being bypassed by a vacuous `0.0` is the point of this ADR. Retuning it
  before activation is exactly the human decision ADR 0005 §3 reserves — and decision 4 is
  what finally makes that decision expressible.
- **Decision-changing when the gate goes live**, all currently latent: the sample floor now
  counts held-out records (~2× stricter); an unmeasurable region blocks a domain;
  out-of-contract scores move from the top bin to bin 0. All strictly fail-closed. The re-axis
  is looser in exactly one direction — mediocre mid bins that inflate today's width but can
  never be operating points no longer block a domain, which is collateral rejection rather
  than protection.
- **Decision-neutral today.** The live store holds 71 records and zero `HUMAN_AUDIT` labels,
  so `build_domain_models` returns `{}`, `tau is None` everywhere, and every domain
  cold-starts to `ESCALATE`. None of these paths execute until audits accumulate.
- Reversible: four `agent_core` modules, no persisted-format impact. `bin_ci_width` is computed
  per run and never written to the store, so no migration is implied.

## Correction — routing complexity (2026-07-31, same-day peer review)

Decision 7 (single-sourcing score→bin routing in `_bin_of`) was implemented in a way that
regressed `fit`'s and `_operating_bin_ci_width`'s complexity from O(n_bins·n) to
O(n_bins²·n): both called `_bin_of`'s own O(n_bins) linear scan from inside a
`for b in range(n_bins)` membership test, turning one O(n_bins) scan per score into
O(n_bins) of them. Measured at ~3.8s for `n_bins=200` on 5000 scores — a real hang/timeout
risk given decision 4 makes `n_bins` an operator-supplied CLI value with no natural upper
bound on cost (it was a hardcoded `10` before this ADR).

Fixed with a shared `_bucket_by_bin(scores, bins)` helper that assigns each score to its bin
exactly once via `_bin_of`, then groups — restoring the pre-regression O(n_bins·n) shape.
Verified bit-for-bit identical to the pre-fix output across every `n_bins` tested; benchmarked
at ~0.02s for the same case (190× faster). `GatePolicyConfig.n_bins` additionally gained
`MAX_N_BINS = 1000` as a resource-safety ceiling — a different rationale from decision 4's
"reject the vacuous endpoint" rule (an arbitrarily large `n_bins` is not *unsafe* the way a
vacuous `risk_target` is, merely expensive, and 1000 is far beyond any realistic per-domain
audit volume).

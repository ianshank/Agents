# Design: merge-gate-health-integrity

Promotes to [ADR 0029](../../../../docs/decisions/0029-operating-region-calibrator-health.md).
Format follows the house ADR idiom (Context / Decision / Consequences).

## Context

`decide()` grants autonomy through five ordered gates (`merge_gate.py:136-173`). The fourth,
`CalibratorHealth.is_trustworthy`, enforces four floors. Measured at `205da23`:

| floor | source | state |
|---|---|---|
| `n >= min_calibration_n` | `outcome_store.py:266` | counted **both** folds while the other three were eval-fold only |
| `ece <= max_ece` | `outcome_store.py:267` | correct, but binned independently of the calibrator it measures |
| `auroc >= min_auroc` | `outcome_store.py:263` | correct, but `min_auroc` had no lower bound, so the single-class sentinel `0.5` could satisfy it |
| `bin_ci_width <= max_bin_ci_width` | `outcome_store.py:271` | **could pass having measured nothing** |

The fourth floor is the defect. `_upper_half_ci_width` scanned bins above raw 0.5 and
accumulated into `widest = 0.0`, so an empty region returned the identity of a `max`-reduction
and satisfied `max_bin_ci_width` vacuously. Reproduced to `AUTO_MERGE` under stock config
(`./review.md` finding 2).

Two constraints shaped the fix. `tau` cannot define the operating region, because `tau` is
computed *from* health (`outcome_store.py:273`) and is therefore unavailable at measurement
time. And the region cannot be defined by re-binning the calibrated values, because two
distinct bins can share an accuracy and pooling them yields an over-narrow interval — the
original reason the code binned by raw score at all (`outcome_store.py:269-270`).

## Decision

### 1. Eligibility is defined by the per-decision Wilson floor, not by `tau` or the raw range

`decide()` can only reach `AUTO_MERGE` if the operating bin satisfies
`wilson_lower(succ, n, z) >= wilson_floor` (`merge_gate.py:170`). So a bin whose Wilson
**upper** bound cannot reach `wilson_floor` can never be an operating point, *whatever `tau`
turns out to be*. That predicate is tau-free, computable at health time, and defined on the
calibrator's own bins — the axis `decide()` actually compares against `tau`.

Using the upper bound rather than the point estimate is what buys the margin for the residual
approximation: eligibility is judged on the eval fold, while `decide()`'s floor uses the full
audit set (~2×), so an extreme fold imbalance could exclude a bin the full set would qualify.
Layer 3 remains the backstop. Health stays measured held-out so "health is always measured
held-out" survives as a one-sentence rule.

### 2. Unmeasurable is `None`, and `None` is untrustworthy

`_operating_bin_ci_width` returns `float | None`; `is_trustworthy` gains
`self.bin_ci_width is not None`. Rejected alternatives:

- **`0.0`** (status quo) — "no evidence" scores identically to "strongest possible evidence".
- **NaN** — has in-repo precedent (`calibration.py:88`), but NaN compares False against every
  bound, which is exactly the one-sided fail-open this subsystem has already been bitten by
  twice (`ChangeContext`, `BinningCalibrator.bin_index`). Reintroducing it here would be
  repeating the mistake in the module that most recently suffered it.
- **`inf`** — needs no type change and is fail-closed, but conflates "not measured" with
  "measured as maximally wide", which is precisely the distinction being restored.

`None` costs a type widening that mypy strict verifies at every use site — the checker finds
missed readers that a sentinel float would hide.

### 3. Sentinel-only was rejected as insufficient, not merely weaker

Returning `None` while keeping the raw-upper-half scan would fix the vacuous pass but leave
the measurement on the wrong axis, converting the fail-open into an arbitrary blocker keyed on
the agent's confidence *scale*: a domain with thousands of perfectly-calibrated audits at raw
0.45 would be permanently ineligible despite a calibrated `p` of 1.0. Health would then depend
on how an agent labels its confidence rather than on whether that confidence is trustworthy —
the same category of error `auroc` exists to catch. Option 1 subsumes the sentinel: `None` is
its degenerate case.

### 4. Policy validation rejects the vacuous endpoint, allows the strict one

A floor that can never reject is worse than no field: the audit log then reports a check that
did no work. A floor that can never accept is a kill switch, which is safe. Hence
`risk_target ∈ [0, 1)`, `wilson_floor ∈ (0, 1]`, `min_auroc ∈ (0.5, 1]`, `n_bins >= 2`.

No cross-field validation. `risk_target <= 1 - wilson_floor` is tempting but would reject
`wilson_floor=0.99, risk_target=0.02` — strictly *more* conservative than the defaults.
Coupling two knobs that measure different quantities (aggregate risk over auto-merges vs. a
per-bin floor) rejects legitimate configurations.

`protected_auto_merge` is neither validated nor exposed. Rejecting `True` would delete an
escape hatch ADR 0005 documents and the suite exercises; a flag would let a workflow disable
the protected-path layer. It stays reachable in-process and now logs a warning.

### 5. The store fails closed; the metrics layer keeps raising

`_bin_of` is the single router. At the store boundary an out-of-contract score floors to bin 0
and never raises — outcome records are deliberately load-tolerant (ADR 0025), and one
malformed historical line must not fail the gate on every change, which raising in `fit` would
cause. `agent_core.calibration` keeps raising because its inputs are computed by this module,
so an out-of-range probability there is a bug, not bad data.

The edge-comparison scan is retained over `min(int(raw * bins), bins - 1)`: they are not
equivalent, since `0.7 * 10 == 6.999999999999999` would silently re-bin every exact decimal
boundary away from the `b / bins` edges the calibrator stores.

## Consequences

**Positive:** the fourth health floor now does work; the measurement is on the axis decisions
are made on; every autonomy value is bounded and human-reachable, satisfying a promise ADR
0005 has made since 2026-06 with no mechanism behind it; the bin count and the routing each
have one home; and the held-out contract — the docstring's central promise — finally has a
test that fails when violated.

**Negative / accepted:** `wilson_floor` now influences health (lowering it admits more bins
and so makes health *stricter* — the knobs balance rather than compound, which is worth
stating because it is unintuitive). Under honest measurement `max_bin_ci_width=0.20` may
require ~50+ high-accuracy audits in every eligible bin and could keep the gate permanently
closed; that is the correct default per ADR 0005 ("the default is to escalate") and the
constraint becoming *visible* instead of being bypassed by a vacuous `0.0` is the point.

**Explicitly not changed:** `SCHEMA_VERSION`, `FrameworkConfig` membership (`GatePolicyConfig`
stays outside it, so `agent_core` remains config-file-free), the `Calibrator` Protocol, the
ADR 0005 enablement checklist, and the gate's default-off posture.

**Reversibility:** every change is local to four `agent_core` modules with no persisted-format
impact. Reverting restores the prior behaviour exactly; no store migration is implied, because
`bin_ci_width` is computed per run and never written to the store.

**Decision-neutral today:** the live store holds 71 records and zero `HUMAN_AUDIT` labels, so
`build_domain_models` returns `{}` and every domain cold-starts to `ESCALATE`. None of these
paths execute. The neutrality is provable by sweeping both revisions over the live store and
diffing the decisions.

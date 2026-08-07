# Spec delta: merge-gate-policy

Capability: the calibrated merge gate's policy configuration and its calibrator-health floors.
Compiles down to F-IDs in `features.yaml` (claimed at land) + `scripts/validations/F_0NN.py`.

## MODIFIED Requirements

### Requirement: Calibrator health is measured on the axis the decision is made on, and an unmeasurable floor never passes

The calibrator-health check SHALL measure interval width over the calibrator bins that could
plausibly be an operating point for `decide()`, and SHALL report the region as **unmeasurable**
rather than as tight when no bin qualifies. A bin whose Wilson **upper** bound cannot reach
`wilson_floor` can never satisfy the per-decision floor whatever `tau` turns out to be, so
eligibility SHALL be defined by that floor rather than by the raw-score range or by `tau`
(which is derived *from* health and therefore unavailable at measurement time). An
unmeasurable region SHALL make the calibrator untrustworthy, so the domain escalates.

Bins SHALL be grouped by bin **index**, never by predicted value: two distinct bins can share
an accuracy, and pooling them would produce an over-narrow interval.

#### Scenario: An empty operating region does not satisfy the width floor

- **WHEN** calibrator health is computed for a domain whose held-out audits contain no bin
  whose Wilson upper bound reaches `wilson_floor`
- **THEN** `bin_ci_width` is reported as unmeasurable, `is_trustworthy` is false, and the
  domain receives no `tau`

#### Scenario: A domain whose audits all sit below the mid-point is still measured

- **WHEN** a domain's entire audit history has `raw_confidence` below 0.5 and a thin
  high-accuracy bin in that range
- **THEN** that bin is measured and its interval width reported honestly, rather than being
  invisible to the health check and defaulting to zero

#### Scenario: A bin that cannot ever be an operating point does not distort the width

- **WHEN** a domain has a wide, confidently-incorrect bin alongside a well-populated
  high-accuracy bin
- **THEN** the reported width is that of the eligible bin only, because `decide()` could never
  operate in the confidently-incorrect one

### Requirement: The sample floor counts the records the health metrics were measured on

`min_calibration_n` SHALL be compared against the number of **held-out** records that produced
the accompanying ECE, AUROC and interval width, not against the domain's total audit count.
The total MAY be retained for diagnostics but SHALL NOT gate any decision.

#### Scenario: A domain does not clear the floor on records it was fitted with

- **WHEN** a domain's audits are split into a fit fold and a held-out fold
- **THEN** the health record's gating sample count equals the held-out fold size, so a domain
  needs enough held-out evidence — not merely enough total records — to be trusted

#### Scenario: The threshold is not fitted on the records that score it

- **WHEN** the fit fold is cleanly separable and the held-out fold carries the same scores with
  anti-correlated labels
- **THEN** the calibrator reflects the fit fold, health reflects the held-out fold, the
  calibrator is judged untrustworthy, and no `tau` is awarded

## ADDED Requirements

### Requirement: Every value governing autonomy is bounded and reachable by a human

`GatePolicyConfig` SHALL validate every tunable at construction, rejecting any value that
would make a floor vacuous — one that cannot reject any input — while accepting the
maximally-strict endpoint of each range, which is a kill switch and therefore safe. Non-finite
values SHALL be rejected explicitly, because they compare False against every bound and would
otherwise pass. `min_auroc` SHALL be bounded strictly above the single-class AUROC sentinel so
that a domain with only one outcome class cannot satisfy the discrimination floor.

The tunables SHALL be reachable from the CI entrypoint without editing library source, since
ADR 0005 reserves their tuning as a human decision. An out-of-range value SHALL be reported as
a usage error, never as an internal error and never as success. `protected_auto_merge` SHALL
NOT be operator-reachable: never auto-merging protected paths is a design invariant, not a
knob, and enabling it in-process SHALL be logged.

#### Scenario: A vacuous risk target is rejected

- **WHEN** `GatePolicyConfig` is constructed with `risk_target` at 1.0
- **THEN** construction raises a configuration error naming the field and echoing the value,
  because a 1.0 target tolerates every error and collapses `tau` to the smallest observed score

#### Scenario: A bad policy flag exits as a usage error

- **WHEN** the merge-gate CI entrypoint is invoked with an out-of-range or non-finite policy flag
- **THEN** it exits with the usage code, never the internal-error code and never the
  proceed-to-merge code

#### Scenario: Policy flags reach the decision

- **WHEN** the entrypoint is invoked against a healthy store with a sample floor raised beyond
  what the store can satisfy
- **THEN** the decision changes from auto-merge to escalate, proving the flag is threaded into
  the decision rather than merely parsed

### Requirement: The bin count is single-sourced and score-to-bin routing is unambiguous

The reliability-bin count SHALL have one library default and SHALL be a policy field passed
explicitly at every call site, so the calibrator, the ECE that measures it, and the
operating-region width cannot silently disagree. A bin count below 2 SHALL be rejected: a
single bin makes the calibrator constant, `tau` equal to that constant, and every change clear
the threshold.

Score-to-bin routing SHALL have a single implementation. At the store boundary an
out-of-contract score SHALL be floored to the lowest bin — fail-closed, treating a score that
cannot be interpreted as no confidence rather than maximum confidence — and SHALL NOT raise,
because outcome records are deliberately load-tolerant and one malformed historical line must
not fail the gate on every change. The metrics layer SHALL continue to raise on out-of-range
input, whose values are computed rather than loaded.

#### Scenario: Fitting and lookup agree on an out-of-contract score

- **WHEN** a calibrator is fitted over a store containing a score above 1.0, below 0.0, or
  non-finite
- **THEN** that score contributes to the lowest bin, the same bin a lookup for it would return,
  so no bin's accuracy is inflated by a record that queries can never reach

#### Scenario: A single-bin policy is rejected

- **WHEN** `GatePolicyConfig` is constructed with a bin count below 2
- **THEN** construction raises a configuration error explaining that one bin makes every change
  clear the threshold

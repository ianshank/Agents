# Spec delta: eval-estimator

Capability: the agent-records calibration report and its interval estimators.
Compiles down to F-IDs in `features.yaml` (claimed at land) + `scripts/validations/F_0NN.py`.

## ADDED Requirements

### Requirement: Proxy–correctness correlation is measured before any variance-reduction estimator is trusted

The system SHALL provide a read-only measurement of the correlation between each candidate
proxy and the authoritative HUMAN_AUDIT correctness label, reported both **marginally** and
**conditionally** on the subsets the gate operates over (score ≥ a candidate threshold; and
per confidence bin), together with the implied prediction-powered effective-sample multiplier
`1/(1−ρ²)`. Degenerate slices (constant proxy, single outcome class, or too few records) SHALL
be reported as degenerate rather than assigned a misleading discrimination value.

#### Scenario: A proxy with conditional signal is distinguished from one without

- **WHEN** proxy-correlation is computed over a store where the calibrated-confidence proxy
  correlates with correctness marginally but is near-constant on the high-score subset
- **THEN** the report shows a materially lower **conditional** ρ than marginal ρ for that
  proxy, and its effective-N multiplier on that subset approaches 1.0

#### Scenario: A degenerate slice is not given a discrimination score

- **WHEN** a proxy is constant, or the audited slice has a single outcome class
- **THEN** the slice is labelled degenerate with the reason, and no AUROC/ρ verdict is emitted

### Requirement: The calibration report supports a selectable interval estimator without changing the gate

The report SHALL accept an `estimator` selector of `wilson` (default) or `ppi++`, and when a
non-default estimator is selected SHALL display **both** the Wilson interval and the selected
interval for each aggregate slice, so the estimator's effect is visible empirically. The
power-tuned PPI++ estimator SHALL reduce to the classical labelled-only estimator when its
tuning parameter is zero, guaranteeing it is asymptotically no wider than Wilson. Selecting an
estimator SHALL NOT alter any merge-gate decision, threshold, or the estimator used inside
`merge_gate`.

#### Scenario: Default behaviour is unchanged

- **WHEN** the report runs with no `--estimator` flag (or `--estimator wilson`)
- **THEN** output is byte-identical to the pre-change Wilson-only report

#### Scenario: PPI++ never widens the interval versus Wilson on the same data

- **WHEN** `--estimator ppi++` runs on a slice whose proxy is uncorrelated with correctness
- **THEN** the PPI++ interval is approximately equal to Wilson (tuning parameter → 0)
- **AND WHEN** the proxy is strongly correlated
- **THEN** the PPI++ half-width is strictly narrower than Wilson

#### Scenario: The gate is untouched

- **WHEN** any report estimator is selected
- **THEN** `merge_gate.decide()` and `threshold_for_risk` still call `wilson_interval`, and no
  gate threshold (`tau`, `wilson_floor`, `risk_target`, `min_calibration_n`) changes

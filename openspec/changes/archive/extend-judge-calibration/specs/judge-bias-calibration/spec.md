# Spec delta: judge-bias-calibration

Capability: measuring an LLM judge's systematic biases, beyond its agreement with human labels,
before it is permitted to gate a release.

## ADDED Requirements

### Requirement: Pairwise judges are tested for answer-order bias

The system SHALL grade every calibration pair in both answer orders and SHALL report the
disagreement and preference-shift rate.

#### Scenario: Swapping order changes the verdict

- WHEN the same candidate pair is judged as A/B and B/A
- AND the winner changes
- THEN the case is recorded as an order-sensitive disagreement

#### Scenario: Order-flip rate is reported alongside agreement

- WHEN a calibration run completes
- THEN the report contains the order-flip rate
- AND a judge with acceptable agreement but a high flip rate is not presented as validated

### Requirement: Judges are tested for verbosity sensitivity

The system SHALL include semantically equivalent concise and expanded answers in the calibration
corpus and SHALL report preference changes attributable to length.

#### Scenario: Length alone changes the preference

- WHEN two answers are semantically equivalent and differ only in length
- AND the judge prefers the longer one
- THEN the verbosity preference delta reflects that preference

### Requirement: Judges are tested for self-preference

The system SHALL record the model family that produced each candidate answer and SHALL report
preference rates broken down by whether the judge and the candidate share a family.

#### Scenario: A judge favours its own family

- WHEN candidates from the judge's own model family win at a materially higher rate
- THEN the report surfaces that breakdown rather than a single pooled preference rate

### Requirement: Uncalibrated judges cannot gate releases

A judge SHALL remain advisory unless its held-out human agreement, statistical power, and configured
bias tolerances all pass.

#### Scenario: A biased judge stays advisory

- WHEN a judge clears its agreement floor but fails a bias tolerance
- THEN it may not gate
- AND the reason names the failing bias check

#### Scenario: An underpowered judge stays advisory

- WHEN the held-out co-determinate sample is below the power floor
- THEN the result is directional only and may not gate

### Requirement: Gating requires a named calibration artifact

The system SHALL require an explicit calibration artifact ID in gating configuration, so that a
gating decision is traceable to the specific calibration run that authorised it.

#### Scenario: Gating without a calibration artifact is rejected

- WHEN a configuration marks a judge as gating without naming a calibration artifact
- THEN the configuration is rejected

### Requirement: Programmatic scorers are evaluated before judges

The system SHALL order evaluation so that deterministic scorers run ahead of LLM judges.

#### Scenario: A deterministic failure does not need a judge

- WHEN a deterministic scorer has already failed an item
- THEN the judge's verdict cannot convert that item into a pass

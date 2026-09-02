# Spec delta: panel-judge

Capability: aggregating N independent member judges into one registered judge whose verdict
carries its own disagreement evidence, abstains rather than guesses, and pays for every
member call it makes.

## ADDED Requirements

### Requirement: A panel aggregates member verdicts under an explicit strategy

The system SHALL provide a judge, registered as `panel`, that builds its member judges from
configuration via the judge registry and SHALL aggregate their scores under an explicitly
named strategy from an enumerated set.

#### Scenario: Median of three members

- WHEN a panel of three mock members scoring 0.2, 0.9 and 1.0 evaluates a prompt
- AND the strategy is `median`
- THEN the verdict score is 0.9

#### Scenario: An unknown strategy is rejected at construction

- WHEN a panel is configured with a strategy outside the enumerated set
- THEN construction raises an error naming the supported strategies

#### Scenario: A single-member panel is rejected at construction

- WHEN a panel is configured with exactly one member
- THEN construction raises an error
- AND the message states that a one-member panel cannot measure disagreement

### Requirement: An abstaining panel reaches results as "no verdict", not as a failure

The system SHALL carry a panel abstention through to the scored result as an absent
pass/fail verdict rather than a failing one, so that "the members disagreed" is distinct
from "the output was bad".

#### Scenario: Abstention does not become a failure

- WHEN a panel abstains for an item
- THEN the resulting score carries no pass/fail verdict
- AND the comment states that the panel abstained

#### Scenario: Abstentions are excluded from the pass rate

- WHEN some items in a run are abstained and the rest pass
- THEN the aggregate pass rate is computed over the non-abstained items only
- AND a run in which every item abstained reports no pass rate at all

### Requirement: Disagreement is surfaced, never averaged away

The system SHALL record every member's verdict and the spread of member scores in the
aggregate verdict's raw payload, and SHALL abstain — returning the configured fail-safe
score with an abstention flag — when the spread exceeds the configured disagreement
threshold.

#### Scenario: The aggregate carries its evidence

- WHEN a panel evaluates a prompt
- THEN the verdict's raw payload contains each member's name, score and reasoning
- AND the spread and standard deviation of member scores

#### Scenario: A disagreeing panel abstains instead of reporting consensus

- WHEN member scores span a spread greater than the configured disagreement threshold
- THEN the verdict score is the configured abstain score
- AND the raw payload marks the verdict as abstained
- AND the reasoning names the spread and the threshold

### Requirement: Member failure degrades to abstention, not fabricated consensus

The system SHALL exclude a member whose evaluation raises from aggregation, record the
failure in the raw payload, and SHALL abstain when fewer members than the configured quorum
survive.

#### Scenario: A failing member is excluded and recorded

- WHEN one member of a panel raises during evaluation
- AND the surviving members meet quorum
- THEN the aggregate is computed over the survivors only
- AND the raw payload records the failed member

#### Scenario: A below-quorum panel abstains

- WHEN member failures leave fewer survivors than the configured quorum
- THEN the panel returns the abstain verdict rather than aggregating the remainder
- AND the reasoning names the survivor count

### Requirement: Panel cost accounting covers every member call

The system SHALL charge the judge budget and the rate limiter once per member call, so that
an N-member panel consumes N reservations per evaluation rather than one.

#### Scenario: A panel cannot under-charge the budget

- WHEN a three-member panel is wrapped by the budget guard with a cap sized for two calls
- THEN the first evaluation triggers the configured budget-exceeded behaviour
- AND a single judge under the same cap evaluates twice

#### Scenario: A nested panel is charged for its members' members

- WHEN a panel's member is itself a panel of three members
- THEN the outer panel's per-evaluation charge counts the inner panel's three calls
- AND not the single member that contains them

### Requirement: Panels of mock members are deterministic offline

The system SHALL evaluate a panel whose members are all mock judges deterministically, with
no network or SDK dependency, so the offline suite exercises the panel end to end.

#### Scenario: Identical configuration yields identical verdicts

- WHEN the same panel of mock members evaluates the same prompt twice
- THEN both verdicts are identical, including the raw payload

#### Scenario: Members are evaluated in declaration order

- WHEN a panel evaluates a prompt
- THEN its members are called in the order they were declared in configuration
- AND the per-member breakdown in the raw payload is in that same order

### Requirement: A panel remains advisory unless a calibration artifact authorises gating

A panel SHALL be treated as one judge for gating purposes: it may not gate unless a gating
configuration names the calibration artifact ID that authorised it, and its calibration
artifact SHALL report panel-level agreement, pairwise member agreement, and abstention rate.

#### Scenario: An unauthorised panel cannot gate

- WHEN a configuration marks a panel as gating without naming a calibration artifact
- THEN the configuration is rejected

#### Scenario: Redundant members are visible

- WHEN a panel's members agree with each other near-perfectly on the calibration corpus
- THEN the calibration artifact reports the pairwise member agreement
- AND the panel is not presented as more validated than a single judge on that evidence

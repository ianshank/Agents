# Spec delta: repeat-reliability

Capability: repeated independent execution of each evaluation item, with reliability metrics that
distinguish a reliable agent from a lucky one.

## ADDED Requirements

### Requirement: Each evaluation item can run multiple independent attempts

The system SHALL accept a configured positive attempt count k and SHALL execute each selected
evaluation item exactly k times unless a fail-closed resource budget terminates the run.

The default SHALL be 1, reproducing the pre-change behaviour, and SHALL be declared on the
configuration model rather than at any runner call site.

#### Scenario: Three attempts retain three distinct records

- WHEN k is 3
- THEN the result store contains attempts 1, 2 and 3 with distinct attempt IDs
- AND no attempt overwrites another attempt

#### Scenario: The default reproduces existing behaviour

- WHEN no attempt count is configured
- THEN each item runs exactly once
- AND the emitted result is byte-identical to the pre-change output

### Requirement: Attempts are independently seeded

The system SHALL derive each attempt's random stream from the run seed, the item index **and** the
attempt index, so that repeated attempts against a deterministic target are not identical by
construction.

#### Scenario: A deterministic target does not fabricate perfect reliability

- WHEN a seeded deterministic target runs with k of 5
- THEN the five attempts do not all share one random stream
- AND a target whose behaviour varies with its random stream produces varying attempt outcomes

#### Scenario: Attempt expansion does not trip the duplicate-item guard

- WHEN k is greater than 1
- THEN the duplicate-item-ID check still evaluates the dataset exactly once
- AND no duplicate-ID warning is emitted for attempts of the same item

### Requirement: Reliability includes pass@k and pass^k

For each evaluation item, the system SHALL report `pass@k` as true when at least one of the k
attempts passes, and `pass^k` as true only when every one of the k attempts passes.

Both SHALL be aggregated per evaluation item and SHALL NOT be pooled across unrelated items.

#### Scenario: One of three attempts succeeds

- WHEN the attempt outcomes are fail, pass, fail
- THEN `pass@3` is true
- AND `pass^3` is false

#### Scenario: Every attempt succeeds

- WHEN all k attempts pass
- THEN both `pass@k` and `pass^k` are true

#### Scenario: Per-item reliability is not averaged away

- WHEN one item passes all k attempts and another passes none
- THEN each item reports its own `pass^k`
- AND the run-level summary does not present a single pooled `pass^k` as if it were a per-item result

### Requirement: Reliability reports distributions

The system SHALL retain and report the distribution of scores, latency, usage, cost, step count and
failure categories across attempts.

#### Scenario: Aggregate output does not hide variance

- WHEN two attempts pass quickly and one times out
- THEN the report includes the timeout
- AND reports the latency distribution rather than only the successful mean

#### Scenario: Raw attempts are persisted before aggregation

- WHEN aggregates are computed
- THEN every raw attempt record already exists in the result payload
- AND the aggregation is a pure function of those records

### Requirement: Reliability metrics can gate a run

The system SHALL allow a gate rule to threshold `pass_at_k` and `pass_power_k` using the existing
gate rule model.

#### Scenario: A reliability gate uses the existing rule shape

- WHEN a gate rule names metric `pass_power_k` with a minimum
- THEN it is validated by the same configuration model as `mean` and `pass_rate` rules
- AND a configuration that introduces an unknown top-level gate key is rejected at parse time

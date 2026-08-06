# Spec delta: trajectory-evaluation

Capability: normalised recording and evaluation of an agent's execution path.
Compiles down to F-IDs in `features.yaml`, claimed at land, and executable
`scripts/validations/F_0NN.py` proofs.

## ADDED Requirements

### Requirement: Agent targets can expose normalised execution trajectories

The system SHALL allow a target result to include an ordered trajectory of model decisions, tool
calls, tool observations, recoverable errors, and terminal outcomes.

The trajectory field SHALL be optional so existing targets and historical results remain valid
without modification.

#### Scenario: A tool-using target records its execution

- WHEN a target calls two tools and receives two observations
- THEN the `TargetOutput` contains those calls and observations in execution order
- AND the original `output`, `error` and `latency_ms` fields remain available

#### Scenario: A text-only target remains compatible

- WHEN a target returns no trajectory
- THEN existing non-trajectory scorers run unchanged
- AND trajectory scorers report a not-applicable verdict rather than a failing score

#### Scenario: Historical results serialise unchanged

- WHEN a run contains no trajectory on any item
- THEN the emitted result JSON is byte-identical to the pre-change output
- AND no `trajectory` key appears in any item payload

### Requirement: Trajectories are normalised before they are compared

The system SHALL canonicalise tool names and tool arguments before matching, SHALL apply a
configurable set of ignored fields for volatile values, and SHALL preserve duplicate calls.

Duplicates carry the precision and loop signal and SHALL NOT be collapsed during normalisation.

#### Scenario: Volatile fields do not defeat a match

- WHEN a reference call and a candidate call differ only in a field configured as ignored
- THEN the two calls compare equal

#### Scenario: Argument key ordering is not significant

- WHEN two calls carry the same nested argument mapping with different key insertion order
- THEN the two calls compare equal

#### Scenario: Duplicates survive normalisation

- WHEN a candidate issues the same call three times
- THEN the normalised trajectory still contains three calls

### Requirement: Trajectories support four matching modes

The system SHALL provide exact, in-order, any-order, and precision/recall matching over normalised
tool calls.

#### Scenario: Exact matching rejects an extra call

- WHEN the reference contains calls A then B
- AND the candidate contains A then X then B
- THEN exact matching fails

#### Scenario: In-order matching tolerates an extra call

- WHEN the reference contains calls A then B
- AND the candidate contains A then X then B
- THEN in-order matching passes

#### Scenario: Any-order matching ignores call order

- WHEN the reference contains calls A and B
- AND the candidate contains B and A
- THEN any-order matching passes

#### Scenario: Precision and recall expose duplicate and missing work

- WHEN a candidate repeats one required call and omits another
- THEN the scorer reports reduced precision and reduced recall separately

### Requirement: Trajectory quality is evaluated separately from matching

The system SHALL score step efficiency, repeated-call loops, and recovery from failed tool calls
independently of reference matching.

#### Scenario: A successful but wasteful trajectory is visible

- WHEN a candidate reaches the correct outcome in fourteen steps
- AND the configured reference budget is four steps
- THEN outcome success may pass
- AND step efficiency reports the excess work

#### Scenario: A failed tool call requires recovery

- WHEN a tool call returns an error
- AND the agent proceeds as though the call succeeded
- THEN the recovery scorer fails

#### Scenario: A retried and recovered failure passes

- WHEN a tool call returns an error
- AND the agent reissues the call or falls back to another tool and then succeeds
- THEN the recovery scorer passes

### Requirement: A missing trajectory is reported as not applicable, never as a failure

When a scorer requires a trajectory and the target emitted none, the system SHALL report an
undetermined verdict rather than a failing one, so that aggregate pass rates are not silently
depressed by inapplicable scorers.

#### Scenario: The aggregate pass rate is not polluted by inapplicable scorers

- WHEN a text-only target is scored by a trajectory scorer
- THEN the score's pass/fail verdict is undetermined
- AND that item contributes no pass and no fail to the scorer's aggregate pass rate
- AND the emitted comment states that no trajectory was present

#### Scenario: The numeric contribution of a missing trajectory is operator-chosen

- WHEN no trajectory is present
- THEN the emitted score value is the configured not-applicable value rather than a fixed literal
- AND the default is documented, because that value still enters the scorer's mean

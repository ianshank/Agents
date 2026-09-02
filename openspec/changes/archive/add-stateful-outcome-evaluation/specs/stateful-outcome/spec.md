# Spec delta: stateful-outcome

Capability: grading an agent against the environment state it produced, rather than against its own
account of what it did.

## ADDED Requirements

### Requirement: Stateful tasks are graded against environment state

The system SHALL allow an evaluation item to declare a state adapter and an expected state
transition.

#### Scenario: A false textual success fails

- WHEN an agent returns "the booking was completed"
- AND the post-run state contains no corresponding booking
- THEN the outcome evaluation fails

#### Scenario: A correct mutation with an unhelpful answer still passes the state check

- WHEN the required record is created
- AND the agent's final text is terse or unhelpful
- THEN the state evaluation passes on its own terms
- AND any text-quality verdict is reported separately

### Requirement: Policy violations fail independently of goal success

The system SHALL support forbidden state transitions that fail the evaluation even when the
requested goal state is reached.

#### Scenario: Goal reached through a forbidden mutation

- WHEN the requested record is created
- AND an unrelated protected record is modified
- THEN goal success is true
- AND policy compliance is false
- AND the overall outcome fails

### Requirement: Evaluation environments are resettable

The system SHALL isolate or reset environment state between attempts.

#### Scenario: Repeated runs do not share mutations

- WHEN the same evaluation item runs k times
- THEN every attempt starts from the declared initial state

#### Scenario: A failed attempt still resets

- WHEN an attempt raises before completing
- THEN the environment is still returned to its declared initial state before the next attempt

### Requirement: State evaluation keeps I/O out of scorers

The system SHALL confine environment access to the adapter seam, leaving scorers as pure functions
over the captured snapshots.

#### Scenario: A scorer receives snapshots, not a live connection

- WHEN a state scorer runs
- THEN it is given the before and after snapshots as data
- AND it performs no I/O of its own

### Requirement: Adapters are registered components

The system SHALL resolve state adapters by registered name from configuration, following the
existing component-registry pattern, so third parties add adapters without editing the engine.

#### Scenario: An unknown adapter name fails at construction

- WHEN a configuration names an unregistered state adapter
- THEN construction raises rather than silently skipping state evaluation

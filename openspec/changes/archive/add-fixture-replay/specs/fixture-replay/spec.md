# Fixture replay

Offline reload of recorded `AgentTrajectory` envelopes. Exact re-score and
counterfactual observation swap are a `TargetRunner`, never a scorer.

## Envelope

### Requirement: Strict envelope parse

The system SHALL parse a `ReplayEnvelope` from JSON with unknown keys raising.
Envelope schema version SHALL be independent of config `SCHEMA_VERSION`.

#### Scenario: Unknown key is refused

- WHEN `envelope_from_dict` is given a mapping that includes a key not in the envelope schema
- THEN it SHALL raise rather than drop the key

#### Scenario: Trajectory round-trip

- WHEN `trajectory_from_dict` is given the output of `trajectory_to_dict` for a two-call trajectory
- THEN the restored `AgentTrajectory` SHALL compare equal, including duplicate tool calls

## Target

### Requirement: Exact replay is deterministic

Exact mode SHALL re-emit the recorded trajectory and output without calling live tools.

#### Scenario: Second run matches the first

- WHEN a `replay` target in exact mode runs the same item twice
- THEN both `TargetOutput.trajectory` values SHALL be equal

### Requirement: Counterfactual is a TargetRunner

Counterfactual replay SHALL pin recorded observations and swap only the declared override.
It SHALL NOT be implemented as a `Scorer`.

#### Scenario: Tagged override

- WHEN `--override tool.search=…` is combined with `--override-when freshness=sensitive`
- THEN only envelopes tagged `freshness=sensitive` SHALL have their search observation replaced

### Requirement: Missing envelope degrades

A missing item SHALL become `TargetOutput.error`, not an uncaught exception (ADR 0038).

#### Scenario: Empty archive

- WHEN the archive contains no envelope for `item.id`
- THEN `run` SHALL return a `TargetOutput` with `error` set and SHALL NOT raise

## Archive

### Requirement: OUTPUT_ROOT confinement

Writes SHALL refuse paths that escape `OUTPUT_ROOT` when that variable is set.

#### Scenario: Parent-segment path

- WHEN an archive write path contains a `..` segment
- THEN the write SHALL raise `ValueError`

## Non-goals (normative)

The system SHALL NOT reconstruct trajectories from Langfuse or Phoenix spans.
The system SHALL NOT add a ClickHouse client to `eval_harness`.
The system SHALL NOT unblock `add-production-eval-flywheel`.

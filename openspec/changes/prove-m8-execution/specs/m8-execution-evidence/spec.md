# Spec delta: m8-execution-evidence

Capability: the M8 (Composability) matrix dimension credits a registered component only when
its protocol method is observed to execute inside an engine pipeline — never merely because
the component's name appears in a validated pipeline configuration.

## ADDED Requirements

### Requirement: An M8 credit requires an observed protocol-method invocation

The system SHALL credit a component for M8 composability only when its protocol method
(`score`, `evaluate`, `load`, `run`, `emit`, or the `snapshot`/`evaluate`/`reset` triple for
state adapters) is observed to execute during a real `EvalEngine` run, via an execution
ledger that patches the registry's single construction choke point rather than by reading a
pipeline's declared configuration.

#### Scenario: A declared-but-uninvoked component is not credited

- WHEN a pipeline configuration names a component (for example a `judge`) alongside scorers
  that never read that component's verdict
- THEN the execution census does not credit that component, even though the pipeline's
  configuration validates and runs to completion

#### Scenario: The gap between declared and executed is published, not hidden

- WHEN a pipeline declares a component that its own scorers never invoke
- THEN `docs/matrix-coverage.md`'s execution-evidence section names the component as
  declared-only, distinguishing it from components that are genuinely invoked

### Requirement: A pipeline that swallows a judge-side network failure is caught

The system SHALL fail the matrix suite when a scorer error is silently converted into a
passing or merely low-valued result during an M8 pipeline run, rather than allowing the
engine's ordinary fail-safe conversion of a scorer exception into a `ScoreResult` to mask a
judge that attempted real network egress.

#### Scenario: A judge client attempting a real connection is caught, not silently scored zero

- WHEN an M8 pipeline for a network-backed judge is run inside the matrix suite's egress
  guard
- AND the judge's construction is not given an injected offline client
- THEN the attempted connection raises inside the matrix suite rather than degrading into a
  `0.0`-valued `ScoreResult` with a `"scorer error: "` comment

### Requirement: The two network judges accept an injected client

The system SHALL provide a `client` dependency-injection parameter on `OpenAIJudge` and
`AnthropicJudge`, matching the seam already shipped on `ModelTarget`, so both can be
exercised inside an M8 pipeline without constructing a real SDK client or importing the SDK
module at all.

#### Scenario: An injected client bypasses SDK construction entirely

- WHEN `OpenAIJudge` or `AnthropicJudge` is constructed with a non-`None` `client` argument
- THEN the corresponding SDK module is never imported and no real client is constructed

#### Scenario: Absent injection preserves existing behaviour

- WHEN `client` is not supplied
- THEN construction behaves exactly as it did before this change — no observable difference
  to any existing caller

### Requirement: Cells known to be infeasible are waived with a stated reason, never silently absent

The system SHALL record an explicit waiver, with a concrete technical reason, for any M8
cell that cannot be exercised in the matrix CI job's current environment, rather than
omitting the cell from the artifact without explanation.

#### Scenario: A judge whose runtime dependency is absent from the CI job is waived, not silently missing

- WHEN a judge's SDK dependency is not installed by the workflow that runs the matrix suite
- THEN the matrix artifact records an explicit waiver naming the missing dependency, rather
  than omitting the component from the execution-evidence section without comment

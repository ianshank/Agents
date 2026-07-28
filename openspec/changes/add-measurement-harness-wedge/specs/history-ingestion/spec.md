# Spec delta: history-ingestion

Capability: ingesting an external repository's merged-PR history and reporting, with honest
uncertainty, whether its merge-risk signal discriminates.
Compiles down to F-IDs in `features.yaml` (claimed at land) + `scripts/validations/F_0NN.py`.

## ADDED Requirements

### Requirement: External PR history is ingested behind a source Protocol

The system SHALL ingest merged-PR history from a target repository via a `PRHistorySource`
Protocol with an offline local-git implementation and a `gh`-backed implementation, using
caller-supplied agent-attribution rules, test globs, and protected-path globs rather than this
repository's own configuration.

#### Scenario: Local repository analysis is fully offline

- **WHEN** the CLI is invoked against a local clone with agent-attributed commits
- **THEN** a report is produced and no network call is made

#### Scenario: A partner's agent prefix is honoured

- **WHEN** ingestion runs against a repository whose agent branches use a prefix other than
  `claude/`, supplied on the command line
- **THEN** those pull requests are attributed to the agent lane and receive a computed
  confidence, rather than defaulting to the human lane at `0.0`

#### Scenario: Truncation is reported, never silent

- **WHEN** ingestion stops early because a page cap, a rate limit, or a per-PR file cap was hit
- **THEN** the result is marked truncated with a reason and per-reason skipped counts, and the
  report displays them

### Requirement: Credentials are read-only and unverifiable scopes fail closed

Ingestion SHALL NOT issue any repository-mutating request. Where token scopes are
introspectable and include a write scope, construction SHALL fail with an explicit scope error
before any data request. Where scopes cannot be introspected, construction SHALL fail unless
the caller explicitly opts in, and the report SHALL record that scopes were unverifiable.

#### Scenario: A write-scoped token is rejected

- **WHEN** a token whose scopes are introspectable and include a write scope is supplied
- **THEN** construction fails with a scope error and no data request is made

#### Scenario: Unverifiable scopes require explicit opt-in

- **WHEN** a token exposes no scope metadata and no opt-in flag is given
- **THEN** construction fails
- **AND WHEN** the opt-in flag is given
- **THEN** ingestion proceeds and the report records the scopes as unverifiable

### Requirement: Ingested records can never carry an authoritative label

Records originating from an external repository SHALL carry only pending or passive labels. No
ingestion or shadow-mode code path SHALL construct, write, or alias the authoritative
human-audit label class.

#### Scenario: A non-passive label is refused at the write boundary

- **WHEN** ingestion attempts to append a record whose label source is the authoritative audit
  class, or any source not in the passive set
- **THEN** the write is refused with an explicit error

### Requirement: Ingested repository text is untrusted data

All ingested repository text SHALL be treated as untrusted: rendered escaped, never interpreted
as instructions, and never passed to a language model by this tooling.

#### Scenario: An instruction-like pull-request body renders inertly

- **WHEN** an ingested pull-request body contains directive text aimed at tooling or models
- **THEN** it appears only as inert escaped text and triggers no behaviour change

### Requirement: Discrimination is reported with an interval, and degeneracy is reported as such

The report SHALL accompany any discrimination estimate with a confidence interval, and SHALL
mark a slice degenerate — naming the reason — rather than emitting a point estimate, whenever
the proxy is constant, the outcomes are single-class, or the sample is below the configured
minimum. Absence of evidence SHALL NOT be rendered as a value that reads as strong evidence.

#### Scenario: A small sample cannot claim discrimination

- **WHEN** a slice yields an above-chance discrimination point estimate on few records
- **THEN** the reported interval includes the no-discrimination value, and the report states
  that discrimination has not been demonstrated

#### Scenario: No upper-half data is not maximal confidence

- **WHEN** a domain's records all fall below the midpoint of the confidence range, leaving the
  upper bins empty
- **THEN** the reported interval width is the no-evidence sentinel rather than zero, and the
  calibrator is not treated as healthy

#### Scenario: A report with no calibration data leads with that fact

- **WHEN** the authoritative-label view contains no records
- **THEN** the report opens by naming what is missing, before any metric table

### Requirement: Report generation is deterministic and model-free

Report generation SHALL be deterministic for identical input history and SHALL make zero
language-model or third-party inference calls.

#### Scenario: Reproducibility

- **WHEN** the same history is analysed twice
- **THEN** outputs are identical except for explicitly designated timestamp fields

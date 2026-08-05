# Spec delta: production-eval-ingestion

Capability: converting sampled production traces, human-takeover cases, explicit user feedback and
incidents into reviewed, versioned, offline regression cases.

## ADDED Requirements

### Requirement: Production failures can become regression candidates

The system SHALL accept a redacted production trace and create a candidate evaluation item
containing the input, relevant trajectory, environment evidence, observed failure category and
provenance.

#### Scenario: A sampled failure becomes a candidate

- WHEN a redacted production trace with a recorded failure is ingested
- THEN a candidate evaluation item exists carrying its provenance
- AND the candidate is not yet part of any gating dataset

### Requirement: Redaction is a precondition of ingestion

The system SHALL validate redaction status deterministically and SHALL reject any record that has
not been redacted.

#### Scenario: An unredacted record is rejected

- WHEN a trace arrives without a valid redaction status
- THEN ingestion fails
- AND no part of the record is written to the corpus

### Requirement: Candidates require human approval

A production-derived candidate SHALL NOT enter a gating golden dataset until a human reviewer
confirms its expected behaviour and data-safety status.

#### Scenario: An unapproved candidate cannot gate

- WHEN a candidate has no approval record
- THEN it is excluded from every gating dataset

### Requirement: Incidents become permanent regression cases

The system SHALL preserve the approved evaluation item and its provenance so a fixed incident
remains covered by future evaluation runs.

#### Scenario: A fixed incident stays covered

- WHEN an approved incident-derived case has been fixed
- THEN the case remains in the corpus
- AND subsequent runs continue to exercise it

### Requirement: Candidates are deduplicated

The system SHALL deduplicate candidates by normalised task and failure fingerprint, so one recurring
production failure does not flood the corpus.

#### Scenario: A recurring failure yields one candidate

- WHEN the same normalised task fails the same way many times
- THEN one candidate is produced, carrying an occurrence count

### Requirement: Online sampling and offline gating remain separate

The system SHALL NOT make request-time allow/deny decisions through the evaluation ingestion
pipeline.

The system SHALL NOT require production network access during deterministic merge CI.

#### Scenario: Merge CI stays offline and deterministic

- WHEN the ingestion CI job runs in merge CI
- THEN it consumes committed fixtures only
- AND it makes no production network call

### Requirement: Corpus growth and staleness are visible

The system SHALL report golden-set growth and identify cases that are no longer exercised.

#### Scenario: A stale case is surfaced

- WHEN an approved case has not been exercised by any run over a configured window
- THEN it is reported as stale rather than silently retained

# Spec delta: distribution

Capability: installing and running the measurement harness outside this repository, and keeping
a partner's data out of this repository.
Compiles down to F-IDs in `features.yaml` (claimed at land) + `scripts/validations/F_0NN.py`.

## ADDED Requirements

### Requirement: The harness is installable and licensed

The repository SHALL carry an OSI-approved licence and a NOTICE that accurately states the
licence of every dependency reachable from the promoted install path, and the harness SHALL
expose a console entry point installable from a git reference.

#### Scenario: Fresh-environment install

- **WHEN** a user installs from a git reference into a clean environment and invokes `--help`
- **THEN** the command succeeds without repository-specific setup

#### Scenario: A non-permissive optional dependency is not misdescribed

- **WHEN** an optional dependency ships under a source-available licence rather than an
  OSI-approved one
- **THEN** the NOTICE names it separately rather than grouping it with permissive dependencies

### Requirement: Committed report artifacts are actually tracked

Sample reports and rendered-output fixtures SHALL be tracked by version control.

#### Scenario: A committed sample report survives a clean checkout

- **WHEN** a sample report is generated and committed, and the repository is cloned fresh
- **THEN** the report file is present, and any test asserting against it passes in CI

### Requirement: External data never enters this repository's calibration corpus

Records ingested from an external repository SHALL be written to a store distinct from this
repository's outcome store, and SHALL NOT be synchronised to this repository's data branch. Any
store synchronisation SHALL require an explicitly supplied remote rather than defaulting to the
current checkout's origin.

#### Scenario: An external run cannot publish into this repository

- **WHEN** ingestion and shadow evaluation run against an external repository
- **THEN** no record is written to this repository's outcome store or pushed to its data branch

#### Scenario: Synchronisation refuses an implicit remote

- **WHEN** a store synchronisation is invoked without an explicit remote
- **THEN** it fails rather than defaulting to the current checkout's origin

### Requirement: Ten-minute first report

A new user following the quickstart SHALL produce their first report within 10 minutes of clone
on commodity hardware.

#### Scenario: Timed quickstart

- **WHEN** the quickstart is executed on a fresh clone
- **THEN** elapsed time to first rendered report is ≤ 10 minutes, recorded in the release pull
  request

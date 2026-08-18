# Spec delta: tool-version-lockstep

Capability: keeping every hand-duplicated copy of the pinned `ruff`/`mypy` versions —
across 7 `pyproject.toml` dev extras and 9 `.github/workflows/skills-ci.yml`
pip-install lines — provably in agreement with one source-of-truth module, without
editing the CI workflow file that carries most of the copies.

## ADDED Requirements

### Requirement: A single module names the pinned tool versions

The system SHALL define the ruff and mypy versions pinned across the fleet in exactly
one module (`scripts/tool_versions.py`) that installs or invokes neither tool and is
importable by any validator.

#### Scenario: The source-of-truth constants are defined

- WHEN `scripts/tool_versions.py` is imported
- THEN it exposes `RUFF_VERSION` and `MYPY_VERSION` as plain string constants
- AND importing it has no side effects (no I/O, no subprocess, no network)

### Requirement: Every pyproject.toml dev-extra pin is checked against the source of truth

The system SHALL assert that every `ruff==`/`mypy==` occurrence in the `dev` extra of
the root `pyproject.toml` and the six sibling packages' `pyproject.toml` files
(`agent-core`, `behavioral-regression`, `flow-protocol`, `flow-corpus`,
`claude-foundation`, `experiments/backend-validation`) equals `scripts/tool_versions.py`'s
constants exactly.

#### Scenario: In-sync pins pass

- WHEN every covered `pyproject.toml`'s `ruff==`/`mypy==` pin equals
  `tool_versions.RUFF_VERSION`/`tool_versions.MYPY_VERSION`
- THEN the validator exits 0

#### Scenario: A drifted pin fails, naming the file and the value found

- WHEN one `pyproject.toml`'s `ruff==` pin is edited to a value other than
  `tool_versions.RUFF_VERSION`
- THEN the validator exits non-zero
- AND the failure message names that file's path and the mismatched version it found

### Requirement: Every skills-ci.yml pip-install pin is checked without editing the file

The system SHALL assert that every `ruff==`/`mypy==` occurrence in
`.github/workflows/skills-ci.yml`'s pip-install lines equals
`scripts/tool_versions.py`'s constants exactly, while never writing to that file.

#### Scenario: In-sync workflow pins pass

- WHEN every `pip install` line in `skills-ci.yml` that pins `ruff`/`mypy` matches
  `tool_versions.py`'s constants
- THEN the validator exits 0

#### Scenario: A drifted workflow pin fails

- WHEN one `skills-ci.yml` job's `mypy==` pin is edited to a value other than
  `tool_versions.MYPY_VERSION`
- THEN the validator exits non-zero, naming that mismatch

#### Scenario: The check never modifies the workflow file

- WHEN the validator runs against `skills-ci.yml`, in either the passing or failing case
- THEN the file's contents and mtime are unchanged on disk
- AND no subprocess is spawned to install, lint, or otherwise act on the pins

### Requirement: A dropped pin fails as loudly as a wrong one

The system SHALL treat a covered file that contains zero occurrences of a tool's pin as
a failure, not a vacuous pass — the same "vacuity is refused" discipline applied
elsewhere to an empty derived census.

#### Scenario: A pin loosened past exact-pin syntax is caught

- WHEN a covered file's `ruff==0.15.20` is changed to `ruff>=0.15.20` (or removed
  outright)
- THEN the validator exits non-zero
- AND the failure message states that no `ruff==` pin was found in that file

### Requirement: The check is read-only, deterministic, and offline

The system SHALL perform this validation by reading committed file text only — no code
execution, no subprocess invocation, no network access — so it produces the same result
on every run against the same tree.

#### Scenario: Repeated runs against an unchanged tree agree

- WHEN the validator is run twice in succession with no file changes between runs
- THEN both runs produce the same exit code and the same set of pass/fail messages

### Requirement: The check is discoverable through the standard validation harness

The system SHALL register this capability in `features.yaml` at the `fast` tier, so
`scripts/validate.py --tier fast` discovers and runs it without a separate invocation.

#### Scenario: The fast-tier harness runs the lockstep check

- WHEN `python scripts/validate.py --tier fast` runs against a tree where this
  capability's feature is `status: done`
- THEN its `validation_command` is executed as part of that run
- AND a failure surfaces as a `scripts/validate.py` failure, not only as a standalone
  script failure a caller would have to know to run separately

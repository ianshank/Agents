# Spec delta: skill-validator-coverage

Capability: `skills/common/skill_validator.py` — the grading engine every other skill's
vendored `validate_skill.py` copy imports from — is measured, gated, lint/type-checked
library code in CI, at the same rigor every other library-shipping skill in this repo is
held to, rather than an untested dependency exempted as if it were a subjective, no-code
skill.

## ADDED Requirements

### Requirement: `skill_validator.py` has a measured, CI-gated coverage floor

`skills-ci.yml` SHALL run `pytest --cov=skill_validator --cov-branch --cov-fail-under=95`
against a dedicated test suite on every change, in a job whose failure blocks the same way
every other library-shipping skill's coverage floor does. Coverage SHALL be measured in the
isolated job environment (`working-directory: skills/common`), not assumed from indirect
exercise by a different suite in a different job.

#### Scenario: A change that drops coverage below the floor fails CI

- **WHEN** a change to `skill_validator.py` or to `skills/common/tests/test_skill_validator.py`
  drops measured branch coverage below 95%
- **THEN** the `common` job's pytest step fails with coverage.py's own
  "Required test coverage of 95% not reached" text

#### Scenario: The root suite's coverage of skill_validator.py is not sufficient by itself

- **WHEN** the root `tests/test_validate_skill.py` suite (which imports the vendored
  `scripts/validate_skill.py` wrapper, not `skill_validator` directly) is the only suite
  exercising `skill_validator.py`
- **THEN** `cd skills/common && pytest tests --cov=skill_validator --cov-fail-under=95` still
  fails, because the `common` job's coverage step never executes the root suite — a dedicated
  suite living under `skills/common/tests/` is required

### Requirement: The two confirmed gaps are directly, not incidentally, tested

`grade_file_exists` SHALL have dedicated tests asserting both its passing and failing
outcomes. `_run_eval`'s subprocess mechanics (the python3/python token rewrite, its
word-boundary exclusions, `shlex.quote`-based shell-quoting, and timeout handling) SHALL be
exercised via real subprocess invocations, not a mock standing in for `_run_eval`.

#### Scenario: grade_file_exists is asserted on, not merely executed

- **WHEN** `skills/common/tests/test_skill_validator.py` runs
- **THEN** at least one test calls `grade_file_exists` with a path that exists and asserts
  `passed is True`
- **AND** at least one test calls it with a path that does not exist and asserts
  `passed is False`

#### Scenario: The python3-token rewrite is proven against a real interpreter, not assumed

- **WHEN** `_run_eval` is called with a command whose leading token is a bare `python3` (or
  `python`)
- **THEN** the real child process reports `sys.executable` as the interpreter that ran it,
  proving the rewrite substituted the validator's own interpreter
- **AND** a command containing a look-alike token that must NOT be rewritten (`python.exe`,
  `/usr/bin/python`, `mypython3`) is proven unchanged by a real `echo` round trip returning
  the literal input text

#### Scenario: A real subprocess timeout is asserted, not assumed from the except clause

- **WHEN** `_run_eval` is called with a command that genuinely runs longer than its timeout
- **THEN** `subprocess.TimeoutExpired` is actually raised by a real, unmocked subprocess call,
  and the test asserts on that real exception rather than a monkeypatched stand-in

#### Scenario: Shell-quoting of a sys.executable path with spaces is proven end to end

- **WHEN** `sys.executable` is a path containing a space (or other shell metacharacters)
- **THEN** `_run_eval` still successfully invokes the interpreter at that path through a real
  `shell=True` subprocess, proving the `shlex.quote` wrapping — not merely the regex
  substitution — is correct

### Requirement: `skill_validator.py` is lint- and type-checked as a standalone target

`skills-ci.yml` SHALL run `ruff check`, `ruff format --check`, and `mypy` against
`skill_validator.py` and `__init__.py` directly, matching the standard every other
library-shipping skill's dedicated job applies to its own implementation files.

#### Scenario: A lint violation in skill_validator.py fails CI

- **WHEN** `skill_validator.py` contains a rule violation from the repo's root ruff
  configuration (inherited via `skills/common/ruff.toml`)
- **THEN** the `common` job's `ruff check` step fails

#### Scenario: A type error in skill_validator.py fails CI

- **WHEN** `skill_validator.py` contains a type error under the root mypy configuration
- **THEN** the `common` job's `mypy` step fails

### Requirement: `common` is CI-covered by a dedicated job, not a documented exemption

`common` SHALL appear as a job name in `skills-ci.yml` and SHALL NOT appear in the
`all-skills` job's `EXEMPT` mapping. The three ADR-0030 "subjective skill" exemptions
(`hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`) SHALL
remain unchanged in both membership and justification.

#### Scenario: The registration + job-coverage guard resolves common via its job, not EXEMPT

- **WHEN** the `all-skills` job's registration + job-coverage guard runs
- **THEN** `common` satisfies the check because `"common"` is a key in `skills-ci.yml`'s
  `jobs` mapping
- **AND** `common` is absent from the `EXEMPT` dict, so no exemption reason is evaluated for it

#### Scenario: The three subjective-skill exemptions are untouched

- **WHEN** the `all-skills` job's `EXEMPT` dict is inspected after this change
- **THEN** it contains exactly `hierarchical-recursive-brainstorm`, `openspec-quality-plan`,
  and `openspec-peer-review`, each with its original, unmodified reason string

### Requirement: `common`'s behavioral tier is deliberately not run, and the reason is stated inline

`common`'s `validate_skill.py` step SHALL run `--tier structural` only. The workflow SHALL
carry an inline comment stating that this is because `common` has no `evals/evals.json` and
no end-to-end task of its own to run behaviorally — a case distinct from both ADR 0030's
library-code tier (which pairs library code with a behavioral task) and its subjective-skill
tier (which has no library code at all).

#### Scenario: The common job never invokes the behavioral tier

- **WHEN** the `common` job's steps are inspected
- **THEN** no step passes `--tier structural,behavioral` or `--tier behavioral`
- **AND** the `--tier structural` step's surrounding comment names the reason (no
  `evals/evals.json`, no end-to-end task) rather than leaving the asymmetry with the other
  library-shipping skills' jobs unexplained

### Requirement: The vendored `common` copy of `validate_skill.py` stays drift-checked

`skills/common/scripts/validate_skill.py` SHALL be byte-identical to the canonical
`scripts/validate_skill.py` and SHALL be tracked by `check_skill_script_drift.py`, either via
explicit registration or the guard's dynamic discovery.

#### Scenario: An edit to the canonical wrapper that isn't mirrored into common's copy fails the drift guard

- **WHEN** `scripts/validate_skill.py` (canonical) is edited without mirroring the change into
  `skills/common/scripts/validate_skill.py`
- **THEN** `python scripts/check_skill_script_drift.py` reports a `"drift"` status for the
  `common` copy and exits non-zero

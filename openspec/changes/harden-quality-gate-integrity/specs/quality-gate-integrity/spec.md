# Spec delta: quality-gate-integrity

Capability: the generated `quality-gate.sh` coverage gate cannot be weakened by anything set
in the calling environment — the threshold, the measured source, and pytest's own option
pass-through are each either a fixed generation-time literal or actively neutralized, and
every case is closed by a test that actually runs the real gate against a real, deliberately
under-covered package.

## ADDED Requirements

### Requirement: The coverage threshold is a generation-time literal

The generated `quality-gate.sh` SHALL interpolate the project's coverage `fail_under` value as
a literal `--cov-fail-under=N` argument, and SHALL NOT reference a `COV_FAIL_UNDER`
environment variable anywhere in the pytest-cov invocation, regardless of how many coverage
sources the project declares.

#### Scenario: A single-source project's coverage command is a literal

- WHEN a project with one declared coverage source and `fail_under = 95` renders its gate
- THEN the `do_coverage` function's pytest invocation contains `--cov-fail-under=95`
- AND it does not contain `$COV_FAIL_UNDER` in any form

#### Scenario: A multi-source project's coverage command is also a literal

- WHEN a project with more than one declared coverage source renders its gate
- THEN the `do_coverage` function's pytest invocation still contains a literal
  `--cov-fail-under=N`
- AND it does not contain `$COV_FAIL_UNDER` in any form

#### Scenario: Setting COV_FAIL_UNDER at runtime has no effect on the outcome

- WHEN a genuinely under-covered package's real, rendered `quality-gate.sh coverage` is
  executed with `COV_FAIL_UNDER=0` set in the process environment
- THEN the command still exits non-zero
- AND the failure output still names the package's real configured threshold, not `0`

### Requirement: The measured coverage source is a generation-time literal

The generated `quality-gate.sh` SHALL interpolate every declared coverage source as a literal,
quoted `--cov=` argument, and SHALL NOT reference a `COVERAGE_SOURCE` environment variable
anywhere in the pytest-cov invocation, in both the single-source and multi-source cases.

#### Scenario: A single-source project's --cov is a literal

- WHEN a project with exactly one declared coverage source renders its gate
- THEN the `do_coverage` function's pytest invocation contains a literal, quoted
  `--cov="<source>"`
- AND it does not contain `$COVERAGE_SOURCE` in any form

#### Scenario: Setting COVERAGE_SOURCE at runtime has no effect on what is measured

- WHEN a real, rendered single-source `quality-gate.sh coverage` is executed with
  `COVERAGE_SOURCE` set to a different, trivially-covered path
- THEN the command still measures the originally configured source
- AND the reported coverage percentage is unaffected by the override

### Requirement: A live env override is warned about, never silently honored or gated on

Whenever `COVERAGE_SOURCE` or `COV_FAIL_UNDER` is set in the environment at gate-run time, the
`coverage` step SHALL print a message to stderr naming the variable and stating that it is
ignored, and the gate's exit code SHALL be unaffected by whether the message was printed.

#### Scenario: An ignored-override notice appears for each variable independently

- WHEN the coverage step runs with both `COVERAGE_SOURCE` and `COV_FAIL_UNDER` set
- THEN stderr contains a distinct notice naming `COVERAGE_SOURCE` as ignored
- AND stderr contains a distinct notice naming `COV_FAIL_UNDER` as ignored

#### Scenario: No notice appears when neither variable is set

- WHEN the coverage step runs with neither `COVERAGE_SOURCE` nor `COV_FAIL_UNDER` set
- THEN stderr contains no "is ignored" notice for either variable

### Requirement: PYTEST_ADDOPTS cannot alter the outcome of a gate stage

Every gate step that invokes `pytest` SHALL clear `PYTEST_ADDOPTS` from its shell environment
before invoking `pytest`, and SHALL first print a notice to stderr when the variable was set,
naming it and stating that the stage has no opt-out.

#### Scenario: A coverage-weakening PYTEST_ADDOPTS does not weaken the coverage step

- WHEN a genuinely under-covered package's real, rendered `quality-gate.sh coverage` is
  executed with `PYTEST_ADDOPTS=--no-cov` (or another coverage-weakening flag) set in the
  process environment
- THEN the command still exits non-zero for the same reason it would with `PYTEST_ADDOPTS`
  unset
- AND stderr contains a notice naming `PYTEST_ADDOPTS` as ignored

#### Scenario: The test step also clears PYTEST_ADDOPTS

- WHEN a project's `test` step (no coverage measurement) renders
- THEN its function body clears `PYTEST_ADDOPTS` before invoking pytest, identically to the
  coverage step

#### Scenario: A hand-maintained pytest invocation carries the same guard

- WHEN a package's hand-maintained `do_extra()` extension (below the generator's marker
  seam) invokes `pytest` directly
- THEN it also clears `PYTEST_ADDOPTS` before that invocation, following the same warn-then-
  unset shell idiom the generator emits

### Requirement: The coverage-exclude pattern for stub bodies is anchored to a whole line

Every package's coverage configuration SHALL exclude a `...` stub body from coverage
measurement only when the ellipsis is the entire content of the line (whitespace aside), and
SHALL NOT exclude a line merely because it contains three consecutive dots as a substring.

#### Scenario: A standalone ellipsis line is excluded

- WHEN a source file contains a line consisting solely of leading whitespace followed by `...`
- THEN that line is excluded from coverage measurement

#### Scenario: An ellipsis embedded in real code is not excluded

- WHEN a source file contains a line where `...` appears as part of other code (for example a
  type annotation, a slice expression, or a one-line stub with a `def` prefix on the same
  line) and that line is never executed by the test suite
- THEN that line is counted as a coverage miss, not silently excluded

#### Scenario: The pattern is identical across every measured package

- WHEN each package's coverage configuration is inspected
- THEN root's `pyproject.toml`, `scripts/.coveragerc`, and every package's `pyproject.toml`
  that declares an ellipsis-stub exclusion all use the same anchored pattern

### Requirement: A real, low-coverage package proves the gate actually gates

The test suite SHALL include at least one fixture package whose real code intentionally falls
short of a configured coverage threshold, and SHALL assert — by actually executing the real
rendered `quality-gate.sh` against real `pytest`/`coverage`, not a mock — that the coverage
step fails for that fixture and passes for a fully-covered counterpart.

#### Scenario: The low-coverage fixture fails with coverage.py's own message

- WHEN the low-coverage fixture's rendered `quality-gate.sh coverage` is executed
- THEN it exits non-zero
- AND its output contains coverage.py's own "Required test coverage" shortfall message

#### Scenario: The high-coverage fixture passes

- WHEN a fixture whose tests fully exercise its code renders and runs `quality-gate.sh
  coverage`
- THEN it exits zero

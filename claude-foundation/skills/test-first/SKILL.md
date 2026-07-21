---
name: test-first
description: Enforces test-driven development - derive observable behaviors from the requirement, write failing tests first (including edge and negative cases), confirm they fail for the right reason, implement the minimum to pass, refactor green, and report red-to-green evidence. Never weakens assertions to make tests pass.
when_to_use: Use when implementing a new feature, fixing a bug, or changing behavior in code that has (or should have) a test suite. Not for docs, config-only changes, or exploratory spikes the user explicitly marks as throwaway.
---

# Test-First Implementation

Write the tests before the implementation, and let the failing tests specify the work.

## Procedure

1. **Derive behaviors.** From the requirement, list the observable behaviors as
   input → expected output pairs (or state transitions / emitted effects). Include
   boundary values. If a behavior cannot be stated as observable, ask the user to
   clarify before writing anything.

2. **Write failing tests.** Using the repo's existing test framework and conventions,
   write unit tests covering the listed behaviors, including at least one edge case
   and at least one negative case (invalid input, error path, or forbidden state).
   If the target project has a committed `scripts/quality-gate.sh`, its test step
   already names the test framework and invocation — take the framework from the
   script instead of re-detecting it. Do not touch implementation code yet.

3. **Confirm red for the right reason.** Run the new tests and verify each fails with
   the expected failure mode — an assertion failure or missing-symbol error that
   points at the unimplemented behavior. A test failing due to a typo, bad import, or
   fixture error is not a valid red; fix the test and re-run. Record the failure
   output. Run this phase test-scoped (e.g. `pytest path/to/test.py::test_x`), never
   through a quality-gate script — the gate is deliberately suite-wide, and the red
   phase needs only your new tests.

4. **Implement minimally.** Write the smallest implementation that makes the new
   tests pass. Resist adding behavior no test demands. Run the new tests plus the
   surrounding suite; all must pass. When the target project has a
   `scripts/quality-gate.sh`, run the suite-wide check as
   `./scripts/quality-gate.sh test` (or `coverage` where a coverage floor applies);
   otherwise run the suite as the repo defines it.

5. **Refactor green.** With tests passing, clean up duplication and naming in both
   implementation and tests. Re-run the suite after each refactor step — via
   `./scripts/quality-gate.sh test` when the project has that gate — and never leave
   the suite red between steps.

6. **Report red → green evidence.** Summarize: the behaviors covered, the initial
   failing output (step 3), and the final passing run (steps 4–5), with the exact
   commands used. When a gate script exists, report the suite-wide runs as the
   stable gate invocations (`./scripts/quality-gate.sh test` / `coverage`) alongside
   the test-scoped red-phase command.

## Rules

- **Never weaken an assertion to make it pass.** Do not broaden equality to
  containment, delete checks, mark tests skipped, or raise tolerances to absorb a
  failure.
- If a test itself is wrong (misreads the requirement, asserts on incidental
  behavior), fix the test — and state the rationale for the change explicitly in
  your report, quoting the requirement it now reflects.
- If the requirement changes mid-task, return to step 1 and re-derive behaviors; do
  not patch tests ad hoc.
- Pre-existing unrelated test failures: note them, do not fix them silently, and do
  not let them block the red/green cycle for your change.

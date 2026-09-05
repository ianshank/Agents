# ADR 0043 — The target executes, the scorers read

**Status:** Accepted · **Date:** 2026-09-05 · **Feature:** F-065
**Change:** `openspec/changes/add-testgen-eval-matrix`
**Supersedes / superseded by:** none

## Context

The harness scores an agent's *answer*, its *path* (F-051 trajectory scorers), and its
*effect on the world* (F-060 state adapters). It had nothing that scores an agent's **test
suite**, which is the artifact this organisation's agents most often produce.

Scoring a generated test suite requires **running** it — against a known-correct
implementation to find false alarms, and against seeded mutants to find what it detects.
That is a different kind of operation from anything the harness did before: it executes
model-authored code.

The source plan proposed putting that execution in the state adapters, on the grounds that
`filesystem` and `sqlite` already touch the outside world. They do not do this.
`state_adapters/__init__.py` says so directly — *"the adapter does not intercept or observe
the target's execution, only what it is told"*. Its protocol is `snapshot` / `evaluate`: it
captures world state *around* `target.run(item)` so a claimed side effect can be verified.
It is a snapshot/diff seam, not an execution sandbox.

## Decision

**Execution belongs to the target. Scorers are pure readers of its evidence.**

```
callable target                          scorers (pure)
──────────────                           ──────────────
run the suite in a subprocess sandbox
against the reference and each mutant ─► TargetOutput.metadata[TESTGEN_EVIDENCE_KEY] ─► read only
                                         test_executability
                                         testgen_mutation_score
                                         testgen_green_on_correct
                                         requirement_obligation_recall
```

This is the `state_transition` pattern with the producer moved from the engine to the
target. It needs no engine change: `TargetOutput.metadata` is already `dict[str, Any]`.

Four consequences are the reason to prefer this shape:

- Scorers stay **deterministic**, so `repetitions > 1` measures the *target's* variance and
  not theirs — the property `add-repeat-reliability-metrics` had to correct a review to
  protect.
- Scorers stay **offline**, so they run in the zero-external-dependency suite unchanged.
- Each scorer is a few dozen lines, so the twenty owed matrix cells are cheap to fill
  honestly rather than discharged with waivers.
- Swapping the execution backend later touches **one target, not four scorers**.

### Execution runs in a subprocess, in a package that had none

`src/eval_harness/` contained no `subprocess` usage before this change. It does now, in
exactly one file (`targets/_suite_runner.py`), and the reason is that a wall-clock limit is
**unenforceable in-process**. A generated test containing `while True:` would hang the
harness, and no signal-based timeout is portable or safe mid-run. A subprocess also
prevents model-authored code from mutating the harness's own module state.

The runner is deliberately dependency-free — stdlib only, no pytest. The harness must not
acquire a runtime test-framework dependency in order to score test suites, and collection
is a dozen lines: import the module, take its `test_*` callables, call each.

### Execution is gated by the existing allowlist, not by a new mechanism

The suite-execution target is a **callable target** named from configuration, so it passes
through the deny-by-default allowlist of ADR 0039. Executing model-authored test code is
the highest-privilege operation in this capability, and it does not get an exemption for
being convenient. The shipped config allowlists `eval_harness.targets.testgen` — the module
prefix, not the `eval_harness` package, which would let any config call anything in the
harness.

### A timeout is evidence, not an exception

A per-item failure is returned as `TargetOutput(error=..., metadata=evidence)`, never
raised. Under the default item-error policy (ADR 0038) a raise aborts the whole run, which
would turn one slow or unrunnable suite into zero measurements for every other item.

### Two definitions that could have been fudged, and were not

**Covered** means the suite actually drove inputs at which the mutant differs. The focal
module is instrumented to record its call arguments, so *"of what it reached"* is measured
rather than assumed. Without this the normalized denominator would have to be guessed, and
the spec requires the payload to name what each figure was computed from.

**Killed** means a test that *passed* against the reference *fails* against the mutant —
not "any test fails". A suite that is red on correct code would otherwise appear to kill
every mutant it was already failing on, turning a false-alarm defect into evidence of fault
detection. `scripts/validations/F_065.py` builds that exact suite and observes 0 kills.

### The shared contract lives in `core`

`TESTGEN_EVIDENCE_KEY` is defined in `core/types.py`, not beside either party. Defining it
in `targets/testgen.py` and importing it from the scorers created a real `scorers → targets`
component edge, which the architecture drift guard caught — the change's own design had
predicted the subpackage would add no edge, and was right about the package mapping while
missing this import. Both components already depend on `core`, so the neutral home costs
nothing.

## Alternatives considered

**Execution inside a scorer.** Rejected: a `Scorer` receives one `(item, output)` pair and
would have to re-execute per scorer, making four subprocess storms out of one, and
destroying the determinism that `repetitions > 1` depends on.

**Execution in a state adapter.** Rejected on the protocol grounds above. The adapter is
told about the world; it does not run the target.

**In-process execution with a signal-based timeout.** Rejected: not portable, not safe to
interrupt arbitrary code mid-run, and it leaves generated code able to mutate harness
state.

**pytest as the runner.** Rejected: it would make a test framework a *runtime* dependency
of the harness, for a collection rule that is a dozen lines of stdlib.

**A `testgen_flake_rate` scorer.** Rejected as unobservable: a scorer sees one attempt.
Flakiness is already expressible as `repetitions: 5` plus `metric: pass_power_k` on
`test_executability` (F-056). Registering a scorer for it would duplicate shipped machinery
and owe five unnecessary matrix cells.

## Consequences

- The harness can now score test suites, and the four scorers discriminate on independent
  axes — verified on a held-out split, where the false-alarm suite moves only
  `testgen_green_on_correct` and the weak suite moves only mutation score and recall.
- `src/eval_harness/` now spawns subprocesses. Confined to one file, invoked from one
  target, reachable only through an allowlisted config entry.
- Every gate rule this capability ships is advisory (`report_only`, F-062). No uncalibrated
  threshold blocks a run; the four bounds are soak starting points in config, and none of
  them appears in the spec delta.
- A new top-level `corpora/` directory. `check_charter_invariants._MISSION_DIRS` is a
  presence check rather than an allowlist, so this raises no charter finding — confirmed by
  reading it, not assumed.

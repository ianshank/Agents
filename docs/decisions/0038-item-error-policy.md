# 0038 — `item_error_policy`: a target failure is data, and `max_workers` decides nothing about it

- Status: **Accepted.**
- Date: 2026-09-04
- Related: ADR 0008 (parallel item execution — the path that dropped items),
  ADR 0031 (additive-change obligations; obligations 1 and 4 constrain this
  change), ADR 0029 (run-level reliability diagnostics — the channel reused
  here), `src/eval_harness/core/_state_lifecycle.py` (the
  never-silently-dropped idiom this generalises), `CHARTER.md` §4.

## Context

`RunSettings.max_workers` silently decided failure semantics.

When a `TargetRunner` raised, the sequential path let the exception propagate
out of `EvalEngine.run()` and aborted the run. The parallel path caught it in
`_run_one_safe`, returned it as a value, and — because `fail_fast` defaults to
`False` — dropped the item from `collected` entirely. The same config and the
same dataset therefore produced two different outcomes depending on one integer.

The parallel outcome was the damaging one. A four-item run whose third item's
target raised returned a `RunResult` with three items, an `aggregate` reporting
`pass_rate = 1.0`, empty `diagnostics`, and no trace of the failure anywhere in
`to_dict()` — so nothing reached the sinks, Langfuse, or a reviewer. Only a log
line survived. `evaluate_gate` reads exactly that `pass_rate`, so a release gate
could be cleared by a run in which a quarter of the items never executed. For a
tool whose entire output is a trustworthiness measurement, a flaky target
raising its own score by deleting its own failures is the worst available
failure mode.

This was not a coverage gap. Both sides of the `if fail_fast:` branch were
exercised, the suite ran 1,966 tests at 98% branch coverage, and
`test_parallel_sequential_same_aggregate` asserted precisely the violated
property — it simply ran on a dataset where nothing failed. The missing artefact
was an oracle, not a test.

Two facts made the fix obvious rather than inventive. The repository had already
written the invariant down, in the CHANGELOG entry for the state-adapter
lifecycle: *"the item always gets a normal, visibly-failed result, never
silently dropped."* And the data model already supported it: `TargetOutput.error`
exists and `RunResult._item_to_dict` already serialises it. The parallel target
path was the one place the invariant had not been applied.

## Decision

**1. `RunSettings.item_error_policy` owns the decision; `max_workers` owns none
of it.**

- `record` (default) — the item is kept as a normal `ItemResult` whose
  `TargetOutput.error` carries the exception and whose `scores` carry a failing
  `item_execution` score. It keeps its submission-order position and its weight
  in every aggregate.
- `raise` — the run aborts on the first such error. This is the legacy
  sequential behaviour, now reachable as an explicit choice rather than as a
  side effect of leaving `max_workers` at 1.

`fail_fast = True` is the stronger statement and continues to abort
immediately. It is folded into the effective policy once, in
`EvalEngine._item_error_policy`, so no execution path re-derives it. That single
fold is what stops the two paths drifting apart again: neither reads `fail_fast`
to decide whether a failure is fatal.

`record` is the default because it is what `fail_fast = False` already
promised. A run configured not to stop at the first failure should not stop at
the first failure, and the sequential path was not honouring that.

**2. The failing score's value is configuration, not a literal.**
`RunSettings.item_error_score` (default `0.0`, bounded `0.0..1.0`) mirrors
`JudgeBudgetConfig.skip_score`, the precedent AGENTS.md cites for exactly this.
The score *name* stays a module constant (`ITEM_ERROR_SCORE_NAME`), matching
`_state_lifecycle`'s `"state_lifecycle"`: a structural identifier that gate
rules address, not a tuning knob.

**3. `StateResetError` remains outside the policy.** It propagates under every
setting. Continuing past a failed reset risks scoring against dirty state, which
is a different and worse failure than a single bad item.

**4. A degraded denominator is reported as a run diagnostic.** A recorded
failure means that item's scorers never ran, so every *other* score's aggregate
covers fewer attempts than the run holds. A gate rule naming one of those other
scores would still read a healthy rate over a quietly smaller sample.
`item_error_diagnostics` emits one `item_execution_failures` entry stating how
many attempts failed.

We deliberately do **not** fabricate a `0.0` for the scorers that never ran.
That would invent data, and the codebase already rejects that pattern where it
matters most: `judges/panel.py` excludes a failed panel member rather than
counting it as a zero vote. Stating the caveat once, at run level, and letting
the consumer decide is the same honesty convention `campaign.py` applies when it
refuses to claim significance below its power floor.

## Consequences

**A clean run is unchanged.** No failure means no `item_execution` score, no
diagnostic, and no `reliability` key in the payload — so ADR 0031 obligation 4
(byte-identical serialisation for the unchanged case) holds. Both properties are
asserted, not assumed.

**A failing run changes, and that is the point.** Runs that previously reported
an inflated `pass_rate` over a silently reduced denominator will now report a
lower one, and gates calibrated against those inflated numbers may go red.
That is the defect surfacing, not a regression. Anyone reconciling historical
results against new ones should expect movement in exactly the runs that had
target failures.

**One existing test changed meaning, and got stronger.**
`test_reset_runs_again_for_the_next_attempt_even_after_a_target_failure`
asserted `reset_calls == 1` and carried an inline comment acknowledging that the
abort was incidental scaffolding. Its name, its docstring, and its
`_CountingTargetThatFailsOnce` helper (*"Raises on its first call, succeeds
thereafter"*) all describe a two-attempt scenario the old engine made
unreachable — the run aborted before the second attempt existed. It now asserts
`reset_calls == 2`, which is what the test always claimed to prove. The legacy
abort is retained as a separate test under `item_error_policy: raise`.

**The escape hatch is real.** Anyone depending on abort-on-target-error sets
`item_error_policy: raise` and gets it on both paths, which is more than the
previous behaviour offered.

## Alternatives considered

**Make the parallel path raise instead of record.** Unifies the two paths and is
a smaller change, but contradicts `fail_fast = False` and throws away the
results of every item that succeeded — strictly less information than recording.

**Keep the drop behind a flag defaulting to the old behaviour.** Preserves
byte-compatibility for failing runs, at the cost of leaving a silent
result-corruption path armed by default and doubling the failure-semantics test
matrix. A silent drop is a defect, not a feature, so it is not preserved.

**Fail the gate whenever any rule's `count` is below the run's attempt count.**
Principled, and it would close the residual denominator gap at the gate itself
rather than only reporting it. Rejected because F-057 deliberately skips a judge
once a programmatic scorer has failed, so a shrunken judge denominator is an
intended outcome and this rule would fire on it constantly. Distinguishing
"skipped by design" from "never ran because the target died" is a gating change
worth making on its own evidence, not folded into this one.

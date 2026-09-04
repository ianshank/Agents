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

- `raise` (default) — the run aborts on the first such error.
- `record` — the item is kept as a normal `ItemResult` whose
  `TargetOutput.error` carries the exception and whose `scores` carry a failing
  `item_execution` score. It keeps its submission-order position and its weight
  in every aggregate.

`fail_fast = True` is the stronger statement and continues to abort
immediately. It is folded into the effective policy once, in
`EvalEngine._item_error_policy`, so no execution path re-derives it. That single
fold is what stops the two paths drifting apart again: neither reads `fail_fast`
to decide whether a failure is fatal.

**`raise` is the default, and an earlier draft of this ADR got that wrong.**
It shipped with `record` as the default, reasoning that `fail_fast = False`
already promised not to stop at the first failure. An adversarial review
disproved it by execution: on `max_workers = 1` — the default — a target failure
that previously hard-aborted the run instead produced a completed run whose gate
**passed**. The change had taken the safe path and made it match the broken one.
`fail_fast = False` governs *scorer* failures; a target exception was always
fatal on the path that behaved correctly. `raise` therefore restores the
sequential behaviour exactly and extends it to the parallel path, which used to
drop the item silently — strictly safer than before on both paths, which is what
this change was for.

**2. The failing score's value is configuration, not a literal.**
`RunSettings.item_error_score` (default `0.0`, bounded `0.0..1.0`) mirrors
`JudgeBudgetConfig.skip_score`, the precedent AGENTS.md cites for exactly this.
The score *name* stays a module constant (`ITEM_ERROR_SCORE_NAME`), matching
`_state_lifecycle`'s `"state_lifecycle"`: a structural identifier that gate
rules address, not a tuning knob.

**3. `StateResetError` remains outside the policy.** It propagates under every
setting. Continuing past a failed reset risks scoring against dirty state, which
is a different and worse failure than a single bad item.

**4. A degraded denominator is reported, and the gate refuses to ignore it.**
A recorded failure means that item's scorers never ran, so every *other* score's
aggregate covers fewer attempts than the run holds. `item_error_diagnostics`
emits one `item_execution_failures` entry stating how many attempts failed.

A diagnostic alone was not enough, and the first version of this change stopped
there. `evaluate_gate` never reads `diagnostics`, so a rule on `acc.pass_rate`
still read 1.0 over the survivors and passed — the precise outcome this ADR
exists to prevent, reproduced by review. `evaluate_gate` now fails when a run
carries item-execution failures, and `GateConfig.allow_item_errors` (default
`False`) is the explicit opt-in for gating over a partial run.

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

**A failing parallel run changes, and that is the point.** A parallel run with a
target failure used to complete and report an inflated `pass_rate` over a
silently reduced denominator; it now aborts, exactly as the sequential path
always did. Anyone whose pipeline depended on that partial result should expect
a loud failure where they previously got a quiet, wrong number. Opting into
`record` returns the partial result, now with the gate refusing to read it
unless `allow_item_errors` says otherwise.

**A sequential run is unchanged.** That is the property an earlier draft of this
change broke and this one restores.

**One existing test changed meaning, and got stronger.**
`test_reset_runs_again_for_the_next_attempt_even_after_a_target_failure`
asserted `reset_calls == 1` and carried an inline comment acknowledging that the
abort was incidental scaffolding. Its name, its docstring, and its
`_CountingTargetThatFailsOnce` helper (*"Raises on its first call, succeeds
thereafter"*) all describe a two-attempt scenario the old engine made
unreachable — the run aborted before the second attempt existed. It now asserts
`reset_calls == 2`, which is what the test always claimed to prove. The legacy
abort is retained as a separate test under `item_error_policy: raise`.

**The escape hatch is real, in the other direction.** Anyone who genuinely wants
partial results from a flaky target sets `item_error_policy: record`, and gets
them on both paths — with the failure visible in `items`, in its own aggregate,
in `diagnostics`, and refused by the gate unless they opt in. That is more than
either path offered before.

## Alternatives considered

**Keep the drop behind a flag defaulting to the old behaviour.** Preserves
byte-compatibility for failing runs, at the cost of leaving a silent
result-corruption path armed by default and doubling the failure-semantics test
matrix. A silent drop is a defect, not a feature, so it is not preserved.

**Fail the gate whenever any rule's `count` is below the run's attempt count.**
Rejected, and still rejected: F-057 deliberately skips a judge once a
programmatic scorer has failed, so a shrunken judge denominator is an intended
outcome and this rule would fire on it constantly. The narrower check adopted
instead — "did any item fail *before* scoring" — distinguishes exactly the two
cases this conflated, using the `item_execution` score as the marker.

**Emit a failing score under every configured scorer's name for a failed item.**
This would make gates work with no gating change at all, and it is the more
convenient answer. Rejected because the item produced no verdict for those
scorers; writing one would invent data. `judges/panel.py` already settles the
precedent in this codebase by excluding a failed panel member rather than
counting it as a zero vote.

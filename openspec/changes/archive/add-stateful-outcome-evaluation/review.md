# Review: add-stateful-outcome-evaluation

**Reviewed:** the externally proposed stateful-outcome change against `b52c696`. Full findings:
`docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

The most valuable of the five changes and the one whose requirements needed least alteration. Two
type-level errors and one architectural misplacement are corrected.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| B4 | `StateAdapter` typed against `EvalContext` | No such type. Uses `RunContext` (`core/types.py:110`) |
| B4 | "Before/after capture in the runner" | `TargetRunner.run` takes no context parameter, so the target has no seam for it. The engine owns the lifecycle |
| — | Adapter I/O unplaced | Confined to the adapter seam so scorers stay pure per-item maps (CHARTER §4 invariant 4) |
| — | Failure semantics unspecified | An adapter error fails the item; a reset failure aborts the run |

## Assumptions challenged

**Can a text-only claim override failed state assertions?** No — that is the entire point, and it is
the first scenario in the spec. The state verdict is independent of the text verdict, and the
composite fails if either fails.

**Are attempts genuinely isolated?** Only once this change lands. `add-repeat-reliability-metrics`
isolates random streams but not environment state, so a side-effecting target leaks between attempts
until state adapters exist. The dependency direction is stated in both proposals rather than left
implicit.

**What happens when the adapter itself fails?** Made explicit, because the tempting default is
wrong: swallowing an adapter error leaves the suite green while measuring nothing. That is the same
vacuous-pass failure mode ADR 0029 found in the merge gate's fourth health floor, where an
unmeasurable metric returned the identity of a `max`-reduction and satisfied its threshold having
observed no data. Fail the item instead.

**Is a reset guaranteed after a crashed attempt?** Yes, and it has its own scenario. Without it the
first failing attempt silently contaminates every subsequent one, and `pass^k` becomes meaningless
in exactly the runs where it matters most.

## Residual risk

- **Snapshot cost.** A full before/after snapshot per attempt multiplies I/O by 2k. For the SQLite
  and filesystem adapters this is bounded and cheap; for a future API-resource adapter it may not be.
  The Protocol permits a cheap change-log snapshot instead of a full capture, and the docs should say
  so before anyone writes a naive remote adapter.
- **Scope creep toward domain validators.** The proposal explicitly defers Salesforce-style domain
  adapters. That boundary needs holding: shipping one domain adapter in-tree invites the harness to
  accumulate business logic it has no charter to own.

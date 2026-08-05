# Review: add-repeat-reliability-metrics

**Reviewed:** the externally proposed repeated-run change, re-verified against `b52c696`. Full
findings: `docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

The capability and its requirements are right, and the insistence on retaining every attempt rather
than only aggregates is the correct instinct. Two defects would have made the change actively
harmful rather than merely broken.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| B14 | Seeding not addressed | `_make_item_rng` folds in `attempt_index`. Without it a deterministic target returns k identical results and the harness reports `pass^k = 1.0` — certifying the exact property the metric exists to detect. A regression test now guards this |
| B14 | Duplicate-ID guard and flat serialisation unmentioned | Attempt expansion moved inside the run loop after the dataset check; attempt identity added to the `to_dict()` payload |
| B3 | Invented a top-level `gates:` block with `minimum`/`maximum` | Does not exist and would not parse under strict `from_dict`. `GateRule.metric` is extended instead |
| B15 | No coverage acceptance | 96% floor stated on the change |

## Assumptions challenged

**Does `pass^k` aggregate per task rather than across unrelated tasks?** It must, and it is now a
requirement with its own scenario. Pooled across a suite, a majority of easy items would mask a task
that fails half the time — inverting the metric's purpose.

**Are attempts genuinely isolated?** Not fully, and this change does not claim otherwise. Random
streams are isolated; *environment* state is not, because no state adapter exists until
`add-stateful-outcome-evaluation`. Until then, a target with side effects will leak between attempts.
Stated as a known limitation rather than papered over, and it is why the state change lists reset
between attempts as one of its own requirements.

**Is cost measured per successful task or per run?** Per successful attempt. Cost per raw run
flatters an agent that fails fast and cheaply.

**Should a resource budget be able to truncate a run?** Yes — fail-closed, and the requirement says
so. The alternative is an unbounded k× multiplication of a live judge bill.

## Residual risk

- **Wall-clock and cost multiply by k.** This is inherent, not a defect, but a suite that switches on
  `repetitions: 5` against a live model target multiplies its bill fivefold. The interaction with
  `judge_budget` (F-022) needs an explicit test: the cap is cumulative per run, so it will bind
  sooner under repetition.
- **`max_workers` semantics shift.** Attempts share the item thread pool, so total concurrency stays
  bounded, but per-item latency distributions will be affected by pool contention. Anyone reading
  latency quantiles off a parallel run needs to know that; documented rather than hidden.

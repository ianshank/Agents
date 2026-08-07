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
| B14 | ~~Seeding not addressed~~ **RETRACTED — the correction was itself wrong** | See "Correction to this review" below. `_make_item_rng` keeps `(base_seed, item_index)`; the requirements become k real `target.run` calls, no harness-injected variance, and a diagnostic when determinism makes `pass^k` uninformative |
| B14 | Duplicate-ID guard and flat serialisation unmentioned | Attempt expansion moved inside the run loop after the dataset check; attempt identity added to the `to_dict()` payload |
| B3 | Invented a top-level `gates:` block with `minimum`/`maximum` | Does not exist and would not parse under strict `from_dict`. `GateRule.metric` is extended instead |
| B15 | No coverage acceptance | 96% floor stated on the change |

## Correction to this review (2026-08-06)

The B14 seeding row above was wrong, and it was wrong in the direction that matters: it would have
made the change actively harmful, which is exactly what this review claimed to be preventing.

Re-verified against the tree:

- `Target.run(self, item: EvalItem)` (`src/eval_harness/targets/__init__.py:22`) receives **only
  the item**. `engine.py:152` calls `self.target.run(item)`. The per-item RNG is placed in
  `RunContext` (`engine.py:240-241`) and passed to **scorers** via `scorer.score(item, output,
  ctx)` — never to the target. Folding `attempt_index` into that seed cannot change target
  behaviour at all.
- `ModelTarget` defaults `temperature=0.0` (`targets/model.py:69`). For a genuinely deterministic
  target, k identical results and `pass^k = 1.0` are **correct**: the agent *is* perfectly
  reliable under that configuration. Nothing is fabricated.

Had it shipped as written, the harness would have injected variance across attempts and reported
it as agent unreliability — an inversion of the metric's purpose, and a worse defect than the one
alleged. The proposal, design and spec are corrected accordingly.

Why the error survived a review whose whole point was catching this class of thing: the finding was
asserted from a plausible reading of `engine.py:41` without ever tracing where the returned RNG is
consumed. One `grep` for `target.run` would have refuted it. Same root cause as the F-051
canonicalisation defects, where the test asserted "does not raise" instead of asserting what was
produced — a claim about behaviour, verified against the shape of the code rather than its
behaviour.

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

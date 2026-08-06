# Change: add-repeat-reliability-metrics

**Status:** proposed · **Date:** 2026-08-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/agent-eval-coverage/REVIEW.md`
**Authorised by:** [ADR 0031](../../../docs/decisions/0031-additive-core-model-extension-for-agent-evaluation.md)
**Depends on:** `add-agent-trajectory-evaluation` (attempt records carry trajectories when present)
**Compiles down to:** `docs/plans/agent-eval-coverage/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

`EvalEngine.run()` executes each item exactly once (`src/eval_harness/engine.py:269`). A single
green run cannot distinguish a reliable agent from a lucky one, and non-determinism is the normal
case for a model-backed target. `run.sample_rate` selects *which* items run, not *how many times*
each runs — the two are unrelated.

`pass@k` (at least one of k attempts succeeds) is the wrong measure for production: it rewards
agents that occasionally get it right. `pass^k` (all k attempts succeed) is the one that predicts
behaviour under real traffic. Neither exists in the tree today.

## What changes

- Add an optional `repetitions` field to `RunSettings`, defaulting to 1 — the current behaviour.
- Add attempt identity (`attempt_id`, `attempt_index`, `item_run_id`) to `ItemResult`, emitted by
  `RunResult.to_dict()`.
- Execute k attempts per selected item through the existing target and scorer lifecycle, retaining
  **every** attempt before any aggregate is computed.
- Add a pure `ReliabilityAggregator` computing per-item success count, empirical pass rate, `pass@k`,
  `pass^k`, mean and quantiles, cost per successful attempt, and score/latency/failure
  distributions.
- Extend the `GateRule.metric` enum with `pass_at_k` and `pass_power_k`.

## Scope / non-goals

- **Non-goal: a new `gates:` config block.** The externally proposed
  `gates: [{metric:, minimum:, maximum:}]` syntax does not exist and would not parse — `from_dict`
  is strict and unknown keys raise (CHARTER §3). The existing `gate.rules` model is extended
  instead (`REVIEW.md` §B3).
- **Non-goal: bumping `SCHEMA_VERSION`.** The addition is optional with a behaviour-preserving
  default, so old configs parse unmodified.
- **Non-goal: trajectory matching or state adapters.** Separate changes.
- **Non-goal: retry semantics.** An attempt is an independent trial, not a retry of a failure.

## Impact

- **Engine execution-loop change** under ADR 0031. Default `repetitions=1` reproduces current
  behaviour exactly, asserted by test.
- **Protected paths:** `config/**`, `src/eval_harness/gating/**`, `tests/**`, `features.yaml`,
  `scripts/validations/**`.
- New F-ID claimed at land with an executable proof.

## The correctness trap this change must not fall into

> **Corrected 2026-08-06.** An earlier revision of this section prescribed folding the attempt
> index into the per-item seed — `(base_seed, item_index, attempt_index)` — to stop a
> deterministic target reporting a "fabricated `pass^k = 1.0`". That prescription is wrong on
> both counts, verified against the tree:
>
> - `Target.run(self, item: EvalItem)` (`targets/__init__.py:22`) takes **only the item**.
>   `engine.py:152` calls `self.target.run(item)`. The per-item RNG goes into `RunContext`
>   (`engine.py:240-241`), which is passed to **scorers** (`scorer.score(item, output, ctx)`),
>   never to the target. Changing the seed therefore cannot alter target behaviour at all.
> - `ModelTarget` defaults `temperature=0.0` (`targets/model.py:69`). For a genuinely
>   deterministic target, k identical results and `pass^k = 1.0` are **correct** — the agent
>   *is* perfectly reliable under that configuration. Nothing is fabricated.
>
> Left uncorrected, the change would have shipped harness-injected variance and called it
> agent unreliability. The real requirements are below.

The trap is not seeding — it is measuring the harness instead of the agent, in either direction.

1. **k genuinely independent `target.run` calls.** The attempts must go through the full
   target-and-scorer lifecycle k times, not be computed once and copied. Verified today: no
   caching layer exists between the engine and the target that could collapse the k draws, and
   none may be introduced without invalidating this metric.
2. **The harness must not manufacture variation.** Perturbing seeds, prompts or parameters
   across attempts would measure harness noise, not agent reliability, and would make `pass^k`
   strictly worse than the truth. Variation must come only from the target's own sampling.
   This cuts both ways for the *scorer* RNG: `RunContext.rng` is a mutable `random.Random`, so
   simply reusing one per-item instance across attempts lets a scorer's draws advance between
   them and change a verdict for identical target output. Each attempt therefore gets the item's
   RNG **freshly reseeded**, so every k-to-k difference is attributable to the target
   (`design.md` records why including scorer noise was rejected).
3. **A structurally uninformative `pass^k` must say so.** When the configuration makes repeated
   attempts identical by construction — `temperature=0`, a fixture/replay target, any target
   documented as deterministic — the run emits a diagnostic alongside the metric:
   *"`pass^k` is 1.0 because sampling is deterministic, not because the agent is reliable."*
   The value is still correct; what would be wrong is reading it as evidence of robustness.
   This is the same failure ADR 0029 records, where a metric reported a pass having measured
   nothing.

Tests assert each of the three: k distinct `target.run` invocations for `repetitions=k`; byte-
identical target inputs across attempts (no injected variance); and the diagnostic present
whenever a deterministic configuration yields `pass^k = 1.0` (`REVIEW.md` §B14).

Two secondary hazards from the same finding: `run()` checks for duplicate item IDs over the
*dataset* list (`engine.py:280-289`), so attempt expansion must happen inside the run loop, after
that check; and `to_dict()` emits `items` as a flat list carrying only `item.id`
(`types.py:86-106`), so attempts serialise as indistinguishable entries unless attempt identity is
added to the payload.

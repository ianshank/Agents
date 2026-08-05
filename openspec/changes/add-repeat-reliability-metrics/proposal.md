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

`_make_item_rng(base_seed, item_index)` (`engine.py:41`) seeds per item only. Running k attempts
without folding the attempt index into the seed makes every deterministic target return k
**identical** results — reporting `pass^k = 1.0` for an agent that was never actually tested k
times. The metric would then certify exactly the property it exists to detect. The seed becomes
`(base_seed, item_index, attempt_index)`, and a test asserts that a deterministic target under
`repetitions>1` produces distinct attempt streams (`REVIEW.md` §B14).

Two secondary hazards from the same finding: `run()` checks for duplicate item IDs over the
*dataset* list (`engine.py:280-289`), so attempt expansion must happen inside the run loop, after
that check; and `to_dict()` emits `items` as a flat list carrying only `item.id`
(`types.py:86-106`), so attempts serialise as indistinguishable entries unless attempt identity is
added to the payload.

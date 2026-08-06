# Design: add-repeat-reliability-metrics

## Configuration

Extends the existing models; no new top-level block.

```yaml
run:
  repetitions: 5          # new optional field on RunSettings, ge=1, default 1
gate:
  rules:
    - score: task_success
      metric: pass_power_k   # GateRule.metric enum extended; min/max unchanged
      min: 0.95
```

The externally proposed syntax was a top-level `gates:` list with `metric` / `minimum` / `maximum`
keys. The repository's model is `GateConfig.rules: list[GateRule]` with `score`, `metric`, `min`,
`max` (`config/models.py:156-171`), and CHARTER §3 records that `from_dict` is strict — unknown keys
raise. A parallel block would both duplicate the gate system and fail to parse
(`docs/plans/agent-eval-coverage/REVIEW.md` §B3).

`repetitions` defaults on `RunSettings`, not at a runner call site (CHARTER §4 invariant 5), and is
optional, so `SCHEMA_VERSION` is untouched.

## Attempt identity

`ItemResult` gains `attempt_index: int = 0`, `attempt_id: str` and `item_run_id: str`. `to_dict()`
emits them per item. Without this, k attempts serialise as k indistinguishable list entries — the
existing payload carries only `item.id` (`types.py:86-106`).

## Seeding — and why it is *not* the lever

> **Corrected 2026-08-06.** This section previously called
> `_make_item_rng(base_seed, item_index, attempt_index)` "the single most important line in the
> change". It is not a lever at all. `Target.run(self, item)` (`targets/__init__.py:22`) receives
> only the item; `engine.py:152` calls `self.target.run(item)`; the per-item RNG is placed in
> `RunContext` (`engine.py:240-241`) and reaches **scorers** only. Re-seeding cannot change what a
> target returns. And `ModelTarget` defaults `temperature=0.0` (`targets/model.py:69`), so for a
> deterministic target `pass^k = 1.0` is the true answer, not a fabricated one.

`_make_item_rng` keeps its current `(base_seed, item_index)` signature. Attempts of one item share
the item's scorer RNG, which is correct: scorer-side randomness is a property of the item under
test, and varying it per attempt would make attempt outcomes differ for reasons that have nothing
to do with the agent.

What the design must guarantee instead:

- **k real invocations.** Each attempt is a separate `target.run(item)` through the full scorer
  lifecycle. No memoisation may sit between the engine and the target — none exists today, and
  introducing one would silently collapse the k draws into one.
- **No harness-injected variance.** The target receives byte-identical input on every attempt.
  Perturbing prompts, parameters or seeds to *induce* variation would measure the harness and
  report a `pass^k` strictly worse than the truth.
- **A determinism diagnostic.** When the configuration makes attempts identical by construction
  (`temperature=0`, a fixture/replay target, or a target declaring itself deterministic), the run
  attaches a note to the metric: *"`pass^k` is 1.0 because sampling is deterministic, not because
  the agent is reliable."* The number stays correct; the diagnostic stops it being read as
  evidence of robustness. ADR 0029 records the cost of omitting exactly this — a metric that
  reported a pass having measured nothing.

## Execution order

Attempt expansion happens **inside** the run loop, after the duplicate-item-ID check
(`engine.py:280-289`), which evaluates the dataset. Expanding before it would emit a spurious
duplicate warning per attempt.

Concurrency: attempts are dispatched through the existing `ThreadPoolExecutor` path alongside items,
so `max_workers` continues to bound total concurrency rather than being multiplied by k. Results are
collected in submission order and sorted, preserving the existing determinism guarantee.

## Aggregation

`ReliabilityAggregator` is a pure function over persisted attempt records — no I/O, no clock, no RNG.
It computes, per item: success count, empirical pass rate, `pass@k`, `pass^k`, mean and quantiles of
score and latency, cost per successful attempt, and a failure-category histogram.

`pass^k` is aggregated **per item**. Pooling across items would let a suite of easy items mask a
task that fails half the time — the exact signal the metric exists to surface.

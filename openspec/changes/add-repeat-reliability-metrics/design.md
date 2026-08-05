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

## Seeding

`_make_item_rng(base_seed, item_index)` becomes `_make_item_rng(base_seed, item_index,
attempt_index)`. This is the single most important line in the change: seeding per item only makes
every attempt of a deterministic target identical, which reports `pass^k = 1.0` for an agent that was
never tested k times. A regression test asserts distinct attempt streams under `repetitions > 1`.

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

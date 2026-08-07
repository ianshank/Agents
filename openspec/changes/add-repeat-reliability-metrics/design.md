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

`_make_item_rng` keeps its current `(base_seed, item_index)` signature — but "attempts share the
item's RNG" is not sufficient as stated, and leaving it there would reintroduce the same class of
bug one level down. `random.Random` is **mutable and stateful**: a scorer that draws from
`ctx.rng` advances it, so attempt 2 sees a different stream than attempt 1 and can return a
different verdict *for identical target output*. That variation is harness-side, and it would be
counted as agent unreliability — exactly what the corrected requirement above forbids.

**Decision: the scorer RNG is reset to the item's seed at the start of every attempt.** Each
attempt receives `_make_item_rng(base_seed, item_index)` freshly constructed, so all k attempts
face an identical scorer environment and every difference in outcome is attributable to the
target. `pass^k` therefore measures *target* reliability, which is what the metric claims to be.

The alternative — letting scorer randomness contribute — was rejected: it conflates two sources of
variance in a single scalar with no way for a reader to tell them apart, and a judge-scorer's
sampling noise would masquerade as agent flakiness. If scorer-noise sensitivity is wanted later it
belongs in its own metric, not folded silently into this one.

What the design must guarantee instead:

- **k real invocations.** Each attempt is a separate `target.run(item)` through the full scorer
  lifecycle. No memoisation may sit between the engine and the target — none exists today, and
  introducing one would silently collapse the k draws into one.
- **No harness-injected variance.** The target receives byte-identical input on every attempt.
  Perturbing prompts, parameters or seeds to *induce* variation would measure the harness and
  report a `pass^k` strictly worse than the truth.
- **A determinism diagnostic**, with a defined contract rather than a vague obligation to "warn".
  *Detection*, in priority order: (1) an optional `is_deterministic` property a target may declare
  on the `TargetRunner` protocol — absent means *unknown*, not `False`, and adding an optional
  member keeps every existing target valid (ADR 0031 obligation 1); (2) derived for `ModelTarget`
  from `temperature == 0.0`; (3) observed, when all k attempts returned byte-identical
  `TargetOutput.output`. *Shape*: a run-level `reliability.diagnostics` list of `{code, message}`,
  code `deterministic_sampling`, emitted only when `pass^k == 1.0` **and** a detection holds, and
  omitted entirely when empty so existing result JSON stays byte-identical. Message: *"`pass^k` is
  1.0 because sampling is deterministic, not because the agent is reliable."* The number stays
  correct; the diagnostic stops it being read as
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

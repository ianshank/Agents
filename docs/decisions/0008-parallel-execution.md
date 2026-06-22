# 0008 — Parallel item execution (ThreadPoolExecutor, sequential fallback)

- Status: **Accepted**
- Date: 2026-06-22
- Related: F-018, `src/eval_harness/engine.py`, `src/eval_harness/config/models.py`

## Context

The evaluation engine processes dataset items sequentially via a list
comprehension (`[self._run_one(item, ctx) for item in items]`). For large
datasets where every item makes a network-bound judge call, this is the dominant
bottleneck: wall-clock time scales linearly with item count even though the work
is embarrassingly parallel.

## Decision

Introduce a `max_workers` field on `RunSettings` (default `1`) and run items
through `concurrent.futures.ThreadPoolExecutor` when `max_workers > 1`.
The sequential path (`max_workers == 1`) remains **exactly** the current list
comprehension — no refactoring, no wrapper — so behaviour is byte-identical.

### Threading safety contracts

1. **Per-item RNG.** Each item receives `random.Random(base_seed + item_index)`
   so the random stream is deterministic regardless of thread scheduling. The
   run-level RNG is used only for sampling (which happens before dispatch).

2. **Langfuse context.** `langfuse_context.get_current_trace_id()` relies on
   `contextvars.ContextVar`, which is NOT propagated to `ThreadPoolExecutor`
   worker threads. The engine gracefully handles `trace_id=None` for parallel
   items — dataset-item linking is skipped rather than crashing. Full per-item
   tracing requires `max_workers=1`.

3. **boto3 / external SDK clients.** boto3 sessions are NOT thread-safe.
   Judges and scorers using boto3 must create a client-per-call or use
   `threading.local()`. This is a scorer/judge contract, not an engine
   responsibility.

4. **Structured logging.** Each worker thread logs via `logging.LoggerAdapter`
   with an `item_id` extra, so log lines remain attributable under concurrency.

5. **`fail_fast`.** On the first exception,
   `executor.shutdown(wait=False, cancel_futures=True)` is called and the
   exception re-raised. Exceptions are collected per-item and do not corrupt
   sibling results.

6. **Result ordering.** Items are submitted with their index. Results are
   collected in submission order (via `enumerate` + sorting), guaranteeing
   deterministic output order regardless of completion order.

7. **Scorer contract.** Scorers MUST be stateless or internally thread-safe.
   Mutable shared state is the scorer's responsibility. The engine makes no
   attempt to serialise scorer calls.

## Consequences

- **Positive:** Network-bound eval runs with N items complete in ≈ N / max_workers
  wall-clock time. The improvement is proportional to IO wait fraction.
- **Positive:** `max_workers=1` is IDENTICAL to the current engine, so existing
  users, tests, and configs are unaffected.
- **Positive:** Per-item RNG ensures deterministic scoring regardless of
  concurrency.
- **Negative:** Langfuse per-item trace linking is unavailable in parallel mode.
  This is an acceptable degradation documented in the config field description.
- **Negative:** Scorers/judges with mutable shared state must be updated for
  thread safety. This is a new contract requirement documented in the Scorer ABC
  docstring.
- **Negative:** Debugging is harder with concurrent execution. `max_workers=1`
  remains the recommended setting for development/debugging.

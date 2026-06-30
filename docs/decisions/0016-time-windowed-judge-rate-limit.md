# 0016 — Time-windowed judge rate limiting (additive, opt-in)

- Status: **Accepted.** Additive on top of F-022; off unless configured.
- Date: 2026-06-30
- Related: F-022 (judge budget cap), F-030, `src/eval_harness/agent_core_adapter/__init__.py`,
  `src/eval_harness/config/models.py`, `agent_core.BudgetLedger`.

## Context

F-022 shipped a **cumulative** per-run cost cap for judge calls and explicitly deferred
time-windowed throttling. But many hosted judge endpoints enforce a requests-per-interval
rate limit, distinct from a total budget: you want to cap *throughput* (e.g. 60 calls/min)
without capping *total* calls, or to do both. `agent_core.BudgetLedger` is purely
cost-cumulative — it has no concept of time — so the window must live in the harness adapter.

## Decision

1. **Additive config** (`JudgeBudgetConfig`): optional `max_per_window: int | None`,
   `window_seconds: float | None`, and `on_rate_limited: str = "block"` (`block` | `skip`).
   A model validator requires the two window fields together (or neither), mirroring the
   existing `_require_cap_when_enabled` guard. The fields are optional, so `SCHEMA_VERSION`
   stays `1.0` and existing configs are byte-identical.
2. **A small sliding-window limiter** (`_SlidingWindowLimiter`) in the adapter: a deque of
   admit timestamps, evicting everything at/under `now - window` and admitting while the
   window holds fewer than `max_per_window`. Time is read from an injected `clock` and
   waiting goes through an injected `sleeper` (defaults `time.monotonic` / `time.sleep`), so
   the whole mechanism is deterministic and unit-tested **without real time**.
3. **Wired into `BudgetedJudge`**: when a limiter is present, each `evaluate` is gated by the
   window *before* the cost reservation — `block` waits (via the sleeper) until a slot frees;
   `skip` returns the existing sentinel verdict. Both run under the same lock that already
   guards the cap reservation, so window bookkeeping stays consistent under parallel
   execution; the inner judge call still runs outside the lock. The rate limit and the cap
   are independent constraints.
4. **`agent_core` stays the cap owner.** The limiter is a thin counter layered on top — not a
   reimplementation of `BudgetLedger`. agent_core is still imported lazily by
   `build_budgeted_judge`, so the offline path pulls nothing extra when budgeting is off.

## Consequences

- **Backwards compatible.** Absent window fields → no limiter, byte-identical behaviour and
  no schema bump. The judge budget (when enabled) still always carries a cumulative cap; the
  window is an optional addition on top.
- **No hard-coded values.** `max_per_window`, `window_seconds`, `on_rate_limited` are all from
  config; `clock`/`sleeper` are injected with stdlib defaults.
- **Tested offline & deterministically.** `tests/test_budgeted_judge.py` covers block/skip,
  recover-after-window, cap independence, the config validators, and the engine wiring with a
  fake clock; `scripts/validations/F_030.py` does the same with no real sleeping. 100% branch
  coverage on the adapter; ruff + mypy clean.
- **Note.** In `block` mode the wait happens under the wrapper lock, so the limiter throttles
  the run *globally* (the intended semantics for a shared endpoint rate limit) rather than
  per-thread.

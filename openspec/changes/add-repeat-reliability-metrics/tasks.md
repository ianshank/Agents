# Tasks: add-repeat-reliability-metrics

`[P]` = protected path; needs `eval-change-approved` + CODEOWNERS review.
Coverage floor: **96%** (root `eval_harness`).

## 1. Configuration — PR 1
- [ ] `[P]` Add `repetitions: int = 1` (ge=1) to `RunSettings` in `config/models.py`.
- [ ] `[P]` Extend `GateRule.metric` to `{mean, pass_rate, pass_at_k, pass_power_k}`.
- [ ] `[P]` Assert an unknown top-level `gates:` key is still rejected at parse time.
- [ ] `[P]` Assert old configs without `repetitions` parse unchanged and `SCHEMA_VERSION` is untouched.

## 2. Attempt identity — PR 1
- [ ] Add `attempt_index`, `attempt_id`, `item_run_id` to `ItemResult`, appended last with defaults.
- [ ] Emit them from `RunResult.to_dict()`.
- [ ] Assert a `repetitions=1` run serialises byte-identically to the pre-change output.

## 3. Execution — PR 1
- [ ] ~~Change `_make_item_rng` to fold in `attempt_index`.~~ **Retracted 2026-08-06** — the RNG
  reaches scorers, never the target (`target.run(item)` takes only the item), so re-seeding cannot
  change what a target returns. `_make_item_rng` keeps its `(base_seed, item_index)` signature.
  See `review.md` → "Correction to this review".
- [ ] Execute each attempt as a separate `target.run(item)` through the full scorer lifecycle.
- [ ] **Test:** `repetitions=5` invokes the target exactly five times for the item — no caching or
  memoisation between engine and target collapses the five draws into one.
- [ ] **Test:** every attempt passes byte-identical input to the target — the harness introduces no
  variance of its own, which would measure the harness rather than the agent.
- [ ] Emit a determinism diagnostic when the configuration makes `pass^k` structurally
  uninformative (`temperature=0`, fixture/replay target): *"`pass^k` is 1.0 because sampling is
  deterministic, not because the agent is reliable."* (ADR 0029's vacuous-pass lesson.)
- [ ] **Test:** that diagnostic is present whenever a deterministic configuration yields
  `pass^k = 1.0`, and absent when variation is genuinely observed.
- [ ] Expand attempts inside the run loop, after the duplicate-item-ID check.
- [ ] Assert no duplicate-ID warning fires for attempts of the same item.
- [ ] Route attempts through the existing thread pool so `max_workers` still bounds concurrency.
- [ ] Persist every raw attempt before any aggregate is computed.

## 4. Aggregation — PR 2
- [ ] Add a pure `ReliabilityAggregator` (no I/O, clock or RNG).
- [ ] Per item: success count, empirical pass rate, `pass@k`, `pass^k`.
- [ ] Distributions: score, latency, usage, cost, step count, failure category.
- [ ] Cost and latency per **successful** attempt, not per raw run.
- [ ] `[P]` Assert `pass^k` is aggregated per item and never pooled across items.

## 5. Gating — PR 2
- [ ] `[P]` Wire `pass_at_k` / `pass_power_k` into `eval_harness.gating`.
- [ ] `[P]` Assert a failing reliability gate exits non-zero.

## 6. Governance — PR 3
- [ ] `[P]` Claim the next free F-ID in `features.yaml`.
- [ ] `[P]` Add an executable `scripts/validations/F_0NN.py` proof.
- [ ] `[P]` Regenerate both `tests/*_baseline.json`.
- [ ] `[P]` Update `architecture.yaml` / `architecture.mmd`.
- [ ] CHANGELOG + user documentation.

## 7. Verification
- [ ] Full gate suite per `docs/plans/agent-eval-coverage/PLAN.md`.
- [ ] End-to-end: one-of-five success passes `pass@5` and fails `pass^5`; all five succeed before `pass^5` passes.

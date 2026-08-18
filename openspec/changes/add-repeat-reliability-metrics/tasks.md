# Tasks: add-repeat-reliability-metrics

`[P]` = protected path; needs `eval-change-approved` + CODEOWNERS review.
Coverage floor: **96%** (root `eval_harness`).

## 1. Configuration — PR 1
- [x] `[P]` Add `repetitions: int = 1` (ge=1) to `RunSettings` in `config/models.py`.
- [x] `[P]` Extend `GateRule.metric` to `{mean, pass_rate, pass_at_k, pass_power_k}`.
- [x] `[P]` Assert an unknown top-level `gates:` key is still rejected at parse time.
      **Correction**: this was empirically false before this change (Pydantic v2 default
      `extra='ignore'` silently dropped unknown top-level keys, including a `gates:` typo of the
      real `gate:` field). Fixed by adding `model_config = ConfigDict(extra="forbid")` to
      `EvalConfig`. Verified safe: `load_config_dict()` always runs `migrate_to_current(raw)`
      before `EvalConfig.model_validate(raw)`, and every real `EvalConfig`-shaped YAML fixture in
      the repo (including the legacy `config/legacy.v0_9.yaml` fixture, post-migration) has zero
      extra keys. Full root `pytest tests/` (root eval_harness suite) passes with this change.
      Test: `test_unknown_top_level_key_rejected` in `tests/test_config.py`.
- [x] `[P]` Assert old configs without `repetitions` parse unchanged and `SCHEMA_VERSION` is untouched.
      Test: `test_config_without_repetitions_parses_unchanged` in `tests/test_config.py`.

## 2. Attempt identity — PR 1
- [x] Add `attempt_index`, `attempt_id`, `item_run_id` to `ItemResult`, appended last with defaults.
- [x] Emit them from `RunResult.to_dict()`.
      **Correction**: emitted *conditionally* (only when `attempt_index is not None`), not
      unconditionally — mirrors the existing `trajectory` precedent (`types.py`, ADR 0031
      obligation 4). Unconditional emission would break the byte-identical-at-`repetitions=1`
      requirement below.
- [x] Assert a `repetitions=1` run serialises byte-identically to the pre-change output.
      Tests: `tests/test_attempt_identity.py` (`test_repetitions_one_serializes_without_attempt_keys`,
      `test_historical_positional_construction_still_works`,
      `test_attempt_identity_is_emitted_when_present`).

## 3. Execution — PR 1
- [x] ~~Change `_make_item_rng` to fold in `attempt_index`.~~ **Retracted 2026-08-06** — the RNG
  reaches scorers, never the target (`target.run(item)` takes only the item), so re-seeding cannot
  change what a target returns. `_make_item_rng` keeps its `(base_seed, item_index)` signature.
  See `review.md` → "Correction to this review".
- [x] Execute each attempt as a separate `target.run(item)` through the full scorer lifecycle.
      New `EvalEngine._run_sequential_repeated` (sequential) and an extended
      `EvalEngine._run_parallel` (unified per-`(item, attempt)` submission, collapsing to the
      original per-item submission at `repetitions=1`).
- [x] **Test:** `repetitions=5` invokes the target exactly five times for the item — no caching or
  memoisation between engine and target collapses the five draws into one.
      Tests: `tests/test_repeated_attempts.py::TestAttemptCount` (sequential + parallel).
- [x] **Test:** every attempt passes byte-identical input to the target — the harness introduces no
  variance of its own, which would measure the harness rather than the agent.
      Test: `TestAttemptCount::test_every_attempt_receives_byte_identical_input`.
- [x] Reset the scorer RNG to the item's seed at the start of each attempt. `RunContext.rng` is a
  mutable `random.Random`; reusing one instance lets a scorer's draws advance between attempts and
  change a verdict for identical target output — harness variance read as agent unreliability.
      Each attempt gets a **freshly constructed** `_make_item_rng(base_seed, item_index)` (not a
      re-seeded shared instance) — same effect, reuses the existing per-item helper unchanged, no
      new seed-mixing scheme. **Real trap caught by an explicit test, not just reasoning**: seeds
      are derived from the loop's own `enumerate()` index, never `ctx.item_index` (which the
      legacy `repetitions=1` sequential path never sets and nothing reads) — verified by
      `test_sequential_repeated_attempts_get_distinct_per_item_seeds`, which reconstructs the
      expected per-item first draw via the real `_make_item_rng` and asserts an exact match.
- [x] **Test:** a deterministic target scored by a scorer that draws from `ctx.rng` reports
  `pass^k = 1.0` — the scorer's randomness does not manufacture flakiness.
      Tests: `TestPerAttemptRngReset` (sequential + parallel) — asserts every attempt of an item
      draws the identical `ctx.rng.random()` value and the derived verdict never flip-flops.
- [x] Add the optional `is_deterministic` property to the `TargetRunner` protocol, appended and
  optional so every existing target stays valid (ADR 0031 obligation 1); derive it for
  `ModelTarget` from `temperature == 0.0`.
      **Correction**: implemented as a plain **method**, not a `@property`. A `runtime_checkable`
      Protocol's `issubclass()` support requires every member to be callable (`typing`'s
      `_is_callable_members_only`) — a property member raises `TypeError: Protocols with
      non-method members don't support issubclass()` at `issubclass(SomeTarget, TargetRunner)`,
      which `tests/test_matrix_eval_tools.py::TestM4Interface` exercises for every registered
      target. Caught by running the full suite, not by inspection — three tests failed on the
      first pass with a property. `ModelTarget.is_deterministic()` returns `None` (unknown, not
      `False`) when `temperature is None` (param omitted; provider default is opaque to the
      harness). Tests: `tests/test_model_target.py` (`test_is_deterministic_*`, 3 cases).
- [x] Emit `reliability.diagnostics` as a list of `{code, message}`, code
  `deterministic_sampling`, only when `pass^k == 1.0` **and** the target is declared, derived or
  observed deterministic: *"`pass^k` is 1.0 because sampling is deterministic, not because the
  agent is reliable."* (ADR 0029's vacuous-pass lesson.)
      **Scope correction**: per `design.md` ("Shape: a run-level `reliability.diagnostics`
      list"), this is a new `RunResult.diagnostics` field, appended last — deliberately **not**
      a call into `ReliabilityAggregator`/`reliability.py`, which doesn't exist until Group 4/PR2;
      this needs one boolean per item, computed locally in a new
      `EvalEngine._reliability_diagnostics`, self-contained within PR1. Detection: (1) declared/
      derived via `target.is_deterministic()`; (2) observed, when unknown, by comparing every
      attempt's `TargetOutput.output` for equality. Returns at most one diagnostic (the message
      carries no per-item detail).
- [x] Omit the `diagnostics` key entirely when the list is empty, so pre-change result JSON is
  byte-identical (ADR 0031 obligation 4).
      `RunResult.to_dict()` emits `payload["reliability"] = {"diagnostics": [...]}` only when
      non-empty. Test: `TestReliabilityDiagnostics::test_absent_at_repetitions_one` asserts
      `"reliability" not in run.to_dict()`.
- [x] **Test:** the diagnostic is present whenever a deterministic configuration yields
  `pass^k = 1.0`, and **absent** for a `temperature=0.7` target that passes all k — that agent was
  genuinely measured.
      Tests: `TestReliabilityDiagnostics` — present (observed tier, `test_present_for_deterministic_target_with_perfect_pass_power_k`),
      present (declared tier, `test_present_via_declared_determinism_without_observing_outputs`),
      absent for a genuinely non-deterministic target that still passes all k
      (`test_absent_for_nondeterministic_target_that_passes_all_k`), and absent when a scorer
      abstains (`passed=None`) on one attempt so pass^k isn't cleanly 1.0
      (`test_absent_when_a_scorer_abstains_on_one_attempt`). `temperature=0.7` itself is unit-
      tested directly on `ModelTarget.is_deterministic()` (`test_is_deterministic_false_at_nonzero_temperature`);
      the engine-level diagnostic tests use the "observed" tier for simpler wiring, since the
      detection logic is identical past `target.is_deterministic()`'s return value.
- [x] Expand attempts inside the run loop, after the duplicate-item-ID check.
- [x] Assert no duplicate-ID warning fires for attempts of the same item.
      Test: `TestDuplicateIdCheck::test_no_duplicate_id_warning_for_attempts_of_the_same_item`.
      Holds by construction: the duplicate check iterates the loaded `items` list, unexpanded;
      attempt expansion happens downstream, in the per-item loops.
- [x] Route attempts through the existing thread pool so `max_workers` still bounds concurrency.
      `_run_parallel` submits one future per `(item, attempt)` pair to the same
      `ThreadPoolExecutor(max_workers=...)`.
- [x] Persist every raw attempt before any aggregate is computed.
      Holds by construction: `results` (every raw `ItemResult`) is fully built before
      `self._aggregate(results)` / `self._reliability_diagnostics(results)` run.

**Also fixed, found while running the full suite (not anticipated in the original task list):**
two existing `tests/test_parallel_execution.py` tests monkeypatch `engine._run_one` with a
two-argument replacement (`(item, ctx)`), which broke once `_run_one_safe` unconditionally passed
the two new kwargs. Fixed by having `_run_one_safe` call `_run_one(item, ctx)` (the exact original
signature) when both new kwargs are `None` — i.e. always, at `repetitions=1` — rather than always
passing them. Restores compatibility with any caller holding the old two-parameter signature,
without touching the two tests.

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

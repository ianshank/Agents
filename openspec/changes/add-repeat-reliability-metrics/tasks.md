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
- [x] Add a pure `ReliabilityAggregator` (no I/O, clock or RNG).
      New `src/eval_harness/reliability.py` — `ReliabilityAggregator.aggregate(items:
      list[ItemResult]) -> ReliabilityReport`, `ReliabilityReport.per_item: tuple[ItemReliability,
      ...]`, one entry per `(item_id, scorer_name)` pair. No `diagnostics` field on this report —
      **scope correction**: `reliability.diagnostics` is fully owned by Group 3's
      `RunResult.diagnostics`/`EvalEngine._reliability_diagnostics` (already shipped in PR1); this
      module has no `target_is_deterministic` parameter either, since that was only needed for
      diagnostics. Test: `TestPurity` asserts calling `aggregate` twice on the same input yields
      an identical (`==`) `ReliabilityReport`.
- [x] Per item: success count, empirical pass rate, `pass@k`, `pass^k`.
      `pass@k`/`pass^k` are booleans (matches `proposal.md`'s "at least one of k … succeeds" /
      "all k … succeed" framing — a single set of k attempts, not multiple probabilistic trials
      to average over). An inconclusive (`passed=None`) attempt counts toward neither a pass nor
      `pass^k`'s "all k" requirement — tested explicitly
      (`test_abstained_attempt_excluded_from_pass_power_k`).
- [x] Distributions: score, latency, cost, failure category.
      **Scope correction**: dropped "usage" and "step count" from this task's own list — neither
      appears anywhere in `design.md`'s actual aggregation contract (only in this checklist line),
      and no target in the tree populates a token-usage field today, so there is no real data to
      aggregate; adding one would be a fabricated schema (`AGENTS.md`'s no-hardcoded-values spirit
      extends to not inventing fields ahead of a data source). `score_quantiles` covers **all**
      attempts (pass and fail alike — the full distribution is the point); `latency_quantiles`
      and `cost_per_success` are successful-attempts-only (see next item). Quantiles are p50/p90/
      p99 via `statistics.quantiles(..., n=100)`, with a single-value special case (`len==1`
      raises in the stdlib but is mathematically well-defined: p50=p90=p99=that value). Failure
      categories: `target_error` (`TargetOutput.error` set), `scorer_fail` (`passed=False`),
      `inconclusive` (`passed=None`) — a 3-category taxonomy grounded entirely in fields that
      already exist, not an invented one.
- [x] Cost and latency per **successful** attempt, not per raw run.
      Test: `test_latency_and_cost_scoped_to_successful_attempts_only` — a failed attempt with
      wildly different latency/cost values does not shift either distribution.
      `cost_per_success` reads `TargetOutput.metadata["cost"]`, an **optional** convention key —
      `None` (not a fabricated `0`) when absent, which is every target in this repo today
      (verified: no target populates it) — tested
      (`test_cost_per_success_none_when_no_target_populates_it`).
- [x] `[P]` Assert `pass^k` is aggregated per item and never pooled across items.
      Test: `TestNeverPooledAcrossItems::test_pass_power_k_is_per_item_not_pooled` — 9 all-pass
      items plus 1 item passing only 1-of-5 attempts; the unreliable item's `pass_power_k` stays
      `False` and its own `pass_rate` (0.2) is directly inspectable — nothing pools it into a
      falsely-reassuring run-wide average, because `ReliabilityReport` only ever exposes per-item
      entries.

## 5. Gating — PR 2
- [x] `[P]` Wire `pass_at_k` / `pass_power_k` into `eval_harness.gating`.
      **Design decision, not pre-specified in tasks.md**: computed **lazily, on demand**, inside
      `evaluate_gate()` itself — `ReliabilityAggregator.aggregate(run.items)` is called at most
      once per `evaluate_gate()` call (memoised across every `pass_at_k`/`pass_power_k` rule in
      the same gate, not just the first), only when a rule actually needs it. Rejected the
      alternative of extending `ScoreAggregate`/`EvalEngine._aggregate()` to eagerly precompute
      these on every run: that would touch `RunResult` serialization again (a second byte-identical
      obligation to protect, on top of Group 2/3's), and would compute reliability stats even for
      runs whose gate never asks for them. The gate value is the **fraction of items** whose own
      per-item `pass_at_k`/`pass_power_k` boolean is `True` — a reduction of `ReliabilityAggregator`'s
      per-item output, never a re-derivation from pooled raw attempts (keeps design.md's
      never-pooled invariant intact one layer up). Tests:
      `tests/test_matrix_eval_tools.py::TestReliabilityGating` (6 cases, including one asserting
      `ReliabilityAggregator.aggregate` is called exactly once for a gate with two reliability rules).
- [x] `[P]` Assert a failing reliability gate exits non-zero.
      `cli.py`'s eval command already maps `GateResult.passed is False` to `return 1` →
      `sys.exit(1)` unconditionally, for every metric — verified this pre-existing wiring needed no
      change; `test_pass_power_k_gate_fails_when_one_item_is_unreliable` asserts
      `GateResult.passed is False` at the `evaluate_gate()` level, the same layer
      `test_gate_fail` (Group 1 precedent) already asserts at for `pass_rate`.

## 6. Governance — PR 3
- [x] `[P]` Claim the next free F-ID in `features.yaml`.
      F-056, as predicted throughout Wave 1 planning — still free at land, confirmed by
      `grep -oE 'F-0[0-9]+' features.yaml | sort -u | tail -1` returning F-055 immediately
      before this edit.
- [x] `[P]` Add an executable `scripts/validations/F_0NN.py` proof.
      `scripts/validations/F_056.py` — 27 checks spanning Groups 1-5 end to end (config
      strictness, attempt identity, exact-call-count + byte-identical input in both dispatch
      paths, per-attempt RNG reset in both dispatch paths, the `ctx.item_index` seed trap,
      `is_deterministic()`, the diagnostic present/absent, `ReliabilityAggregator`'s pass@k/pass^k
      and never-pooled invariant, and gating). All 27 pass on a clean run; exits 0.
- [x] `[P]` Regenerate both `tests/*_baseline.json`.
      Ran `python tests/test_public_surface.py` / `python tests/test_plugin_registry_surface.py`
      (no `--update` needed — both passed unchanged): neither `reliability.py` nor the
      `gating/__init__.py` additions declare `__all__`, and no new scorer/target/judge/dataset/
      sink was permanently registered, so neither tracked surface actually changed. Verified,
      not assumed — both suites were run and their pass/fail read directly.
- [x] `[P]` Update `architecture.yaml` / `architecture.mmd`.
      New `reliability: [core]` component; `gating: [config, core, reliability]` (gating imports
      `ReliabilityAggregator` on demand). **Correction to this plan's own earlier prediction**
      ("engine/gating edges into it"): `engine.py` has **no** edge into `reliability` — its
      `_reliability_diagnostics` stayed a deliberately local, self-contained check (see Group 3),
      so only `gating` gained the edge. Verified against the real import graph, not just declared:
      `python skills/architecture-drift-guard/scripts/drift_check.py --manifest architecture.yaml`
      reports "No undocumented dependencies. Architecture matches the manifest." — the one
      pre-existing warning (`engine -> agent_core_adapter`, declared-but-unused) predates this
      change (confirmed via `git stash`). `architecture.mmd` regenerated via `mermaid_gen.py`, not
      hand-edited; freshness re-verified after.
- [x] Also regenerated `docs/matrix-coverage.md` (`python tests/test_matrix_coverage.py --update`)
      — stale after the new M8 pipeline (Group 7) and after deleting the stale `FOLLOW_ON` row
      below. Not originally listed in this task, but the same "generated artifact, regenerate via
      its own tool" discipline as the two items above.
- [x] Deleted the stale `FOLLOW_ON` entry for this change in `tests/_matrix_coverage.py` (not
      enforced by the guard, but stale bookkeeping once this lands) — its three named obligations
      are now genuinely satisfied, not just declared satisfied: the gating floor already covered
      M1/M2/M6 and this change's pass_at_k/pass_power_k tests ride on it
      (`TestReliabilityGating`); `ReliabilityAggregator`'s determinism is tested
      (`TestPurity.test_calling_twice_yields_identical_results`); and the M8 pipeline now exists
      (`PIPELINES["repeated_attempts"]`, Group 7).
- [x] CHANGELOG + user documentation.
      `CHANGELOG.md` `[1.3.0-dev] > Added` — new top entry (this change is the most recent).

## 7. Verification
- [x] Full gate suite per `docs/plans/agent-eval-coverage/PLAN.md`.
      `./scripts/quality-gate.sh all` — PASS (root: 1677+ passed, coverage 98%+/floor 96%;
      scripts: coverage 95%+/floor 85%); `ruff check .` and `python -m mypy src/eval_harness tests
      scripts` both clean across the whole repo, not just touched files.
- [x] End-to-end: one-of-five success passes `pass@5` and fails `pass^5`; all five succeed before
      `pass^5` passes.
      `tests/test_matrix_eval_tools.py::TestM8Composability::test_m8_repeated_attempts_pipeline` —
      a real `EvalEngine.from_config(...).run()` over a `repetitions=5` config with one item that
      always succeeds (`pass@5`/`pass^5` both `True`) and one that succeeds on exactly one of five
      attempts (`pass@5` `True`, `pass^5` `False`), through `ReliabilityAggregator` AND
      `evaluate_gate()` together — not each in isolation. Also exercised directly (hand-built
      `ItemResult`s, no engine) in `tests/test_reliability.py::TestBasicCounts` and
      `scripts/validations/F_056.py` check 8.

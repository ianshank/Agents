# Tasks: add-stateful-outcome-evaluation

`[P]` = protected path. Coverage floor: **96%** (root `eval_harness`).

## 1. Contracts — PR 1
- [ ] Add `StateSnapshot` and `StateEvaluation` value objects.
- [ ] Add the `StateAdapter` `Protocol` typed against `RunContext`.
- [ ] Add a `STATE_ADAPTERS` registry alongside the five existing registries.
- [ ] Assert an unregistered adapter name raises at construction.

## 2. Engine lifecycle — PR 1
- [ ] Reset → snapshot(before) → run → snapshot(after) → evaluate, per attempt.
- [ ] Assert reset runs even when an attempt raises.
- [ ] Assert an adapter error fails the item rather than degrading to no-opinion.
- [ ] Assert state does not leak between attempts under `repetitions > 1`.

## 3. Scorers — PR 2
- [ ] `[P]` Deterministic state-transition scorer, pure over the two snapshots.
- [ ] `[P]` Policy-violation scorer failing independently of goal success.
- [ ] `[P]` Assert a false textual success fails when the mutation did not occur.
- [ ] `[P]` Assert goal-reached-via-forbidden-mutation reports goal true, policy false, overall fail.

## 4. Adapters — PR 2
- [ ] `[P]` In-memory mapping adapter.
- [ ] `[P]` Filesystem sandbox adapter, writes confined to a temp root.
- [ ] `[P]` SQLite transaction adapter with an example fixture.
- [ ] `[P]` In-process mock HTTP adapter — no network on the offline path.
- [ ] `[P]` Fault-injection tests for raise-during-snapshot, raise-during-reset, raise-mid-run.

## 5. Governance — PR 3
- [ ] `[P]` Claim the next free F-ID; add an executable `scripts/validations/F_0NN.py` proof.
- [ ] `[P]` Add the state-adapter component and its edges to `architecture.yaml`; regenerate `architecture.mmd`.
- [ ] `[P]` Regenerate both `tests/*_baseline.json`.
- [ ] CHANGELOG + user documentation.

## 6. Verification
- [ ] Full gate suite per `docs/plans/agent-eval-coverage/PLAN.md`.
- [ ] End-to-end: an agent produces correct text but fails state evaluation.
- [ ] End-to-end: state resets between repetitions.

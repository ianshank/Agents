# 0036 — Decompose `engine.py` and `agent_core_adapter` into focused modules

- Status: **Accepted.**
- Date: 2026-08-30
- Related: `scripts/check_size_budget.py`, ADR 0019 (size-budget gate; the
  `store_sync/` package-split precedent this follows), ADR 0008 (parallel
  item execution — the code being relocated here), `CHARTER.md` §4
  invariant 1.

## Context

`src/eval_harness/engine.py` sat exactly at the 500-line hard cap enforced by
`scripts/check_size_budget.py` (ADR 0019), and its own
`_run_reliability_diagnostics` docstring already recorded one prior
extraction "to stay under the size budget" — the file was full again. It
mixed a composition-root factory (`from_config`), single-item execution,
aggregation, and two independent execution strategies (parallel via
`ThreadPoolExecutor`, sequential-with-repetitions) in one class.
`src/eval_harness/agent_core_adapter/__init__.py` (469 lines) similarly
bundled four largely independent concerns: adapter config, the
harness↔agent-core bridge, generic judge cost/rate-limiting, and
judge-calibration gate authorization.

A repo-wide audit — ranking "god file" candidates by blast-radius rather than
raw line count, since the size gate already suppresses naive growth —
identified both as the highest-leverage, lowest-risk decomposition targets:
every eval run goes through both files, and neither is on the protected-paths
list (`scripts/eval_protected_paths.py`), so no `eval-change-approved` label
is required.

## Decision

Split both files along their existing internal seams, following the
`store_sync/` package-split precedent from ADR 0019 exactly (types / pure
logic / I/O-or-execution layering, with the top-level file or `__init__.py`
kept as a thin CLI-or-re-export shim so every previously-importable name
keeps resolving):

- **`engine.py`** (500 → 425 lines): the two execution strategies
  (`_run_parallel`, `_run_sequential_repeated`) and `_make_item_rng` move to
  a new `src/eval_harness/core/_execution_strategies.py`, matching the
  existing `core/_reliability_diagnostics.py` / `core/_state_lifecycle.py`
  naming and shape precedent — pure functions, explicit leaf parameters
  only, never `self`, `EvalConfig`, or `EvalEngine`. `core` has zero
  declared dependencies in `architecture.yaml`; passing the config or engine
  in, even only under `TYPE_CHECKING`, would create an undeclared import
  edge and fail the architecture-drift gate
  (`skills/architecture-drift-guard`). `EvalEngine` keeps
  `_run_parallel`/`_run_sequential_repeated` as thin wrapper methods that
  build a `RunContext` via a `make_ctx` closure and delegate.
  `_run_one`/`_run_one_safe` deliberately stay on `EvalEngine`:
  `tests/test_parallel_execution.py` monkeypatches `engine._run_one` on a
  live instance and relies on the parallel path resolving it dynamically
  through `self`, and the required split alone already frees enough
  headroom.
- **`agent_core_adapter/__init__.py`** (469 → 48 lines): split by concern
  into `config.py` (`AdapterConfig`), `bridge.py` (the harness↔agent-core
  bridge), `budget.py` (judge cost/rate-limiting — keeps its existing
  lazy/`TYPE_CHECKING` agent-core imports, so the offline path still never
  pulls in agent-core unless budgeting is enabled), and
  `gate_authorization.py` (judge-calibration gate authorization).
  `__init__.py` is now a thin re-export shim preserving the exact `__all__`
  surface and the fail-fast "agent-core is required" `ImportError`.

**This is not a CHARTER §4 invariant-1 amendment.** Invariant 1 exists to
keep new component *types* flowing through the registries instead of being
hardcoded into the engine; it does not freeze `engine.py`'s bytes. Every
extraction here is a pure, behavior-preserving code move — no new component
type, no new extensibility surface, no public-API change
(`tests/test_public_surface.py` pins the unchanged `__all__`), verified via
the full quality-gate suite plus `skills/architecture-drift-guard`'s drift
check confirming zero new cross-component import edges. No §3 Ratified
Amendment entry is warranted; this ADR exists to satisfy
`skills/repo-invariant-review`'s path-based `core_model_change` check (any
`engine.py` diff with no ADR in the same change is flagged, regardless of
what changed) and to record why that check's default remedy — a ratified
amendment — does not apply here.

## Consequences

- Both files have real headroom under the 500-line cap again; the next small
  feature addition to either doesn't immediately trip the size-budget gate.
- Four independent concerns in `agent_core_adapter` (config, bridge, budget,
  gate authorization) are now independently readable, testable, and
  reviewable, rather than one 469-line file.
- The remaining god-file candidates from the same audit —
  `src/eval_harness/judges/__init__.py`, `src/eval_harness/scorers/__init__.py`
  (both protected paths), and `skills/common/skill_validator.py` (synced
  byte-for-byte into every skill; needs `check_skill_script_drift.py`
  updated first) — are deliberately deferred; tracked in `NEXT_STEPS.md`.

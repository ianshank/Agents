# Tasks: add-agent-trajectory-evaluation

`[P]` means the task touches a protected path and needs the `eval-change-approved` label plus
CODEOWNERS review (`scripts/eval_protected_paths.py`).

Coverage floor for everything in this change: **96%** (root `eval_harness`, `pyproject.toml:162`).

## 1. Contracts — PR 1 (unprotected)

- [ ] Add `ToolCallRecord`, `TrajectoryStep` and `AgentTrajectory` frozen value objects.
- [ ] Append `trajectory` to `TargetOutput` as its last field, leaving the dataclass mutable and the
      existing field order untouched.
- [ ] Export the three new names from `core/__init__.py`'s `__all__`.
- [ ] Extend `RunResult.to_dict()` to emit the trajectory only when present.
- [ ] Assert historical positional `TargetOutput(output, latency_ms, error, metadata)` construction
      still works.
- [ ] Assert a trajectory-free run serialises byte-identically to the pre-change output.

## 2. Normalisation — PR 1 (unprotected)

- [ ] Add `core/_trajectory.py`: pure, no I/O, no SDK imports.
- [ ] Configurable tool-name canonicalisation.
- [ ] Recursive argument canonicalisation with stable key ordering.
- [ ] Configurable ignored-field set, applied at any nesting depth.
- [ ] Tests for nested mappings, sequences, nulls, and duplicate calls surviving normalisation.

## 3. Matching scorers — PR 2

- [ ] `[P]` Register `trajectory_exact`.
- [ ] `[P]` Register `trajectory_in_order`.
- [ ] `[P]` Register `trajectory_any_order`.
- [ ] `[P]` Register `trajectory_precision_recall`, reporting precision and recall separately in
      `ScoreResult.metadata`.
- [ ] `[P]` Validate scorer configuration at construction time, raising on unknown modes.
- [ ] `[P]` All seven scorers live in `scorers/trajectory.py`; `scorers/__init__.py` imports it for
      registration only, keeping both files under the 500-line hard limit.

## 4. Behavioural scorers — PR 2

- [ ] `[P]` Register `trajectory_step_efficiency`.
- [ ] `[P]` Register `trajectory_loop_detection`.
- [ ] `[P]` Register `trajectory_recovery`.
- [ ] `[P]` Test tool error followed by: success, retry, fallback, and false success.
- [ ] `[P]` Test that a missing trajectory yields `passed=None` with the configured `on_missing`
      value and an explanatory comment.

## 5. Integration — PR 1 (sinks) and PR 2 (baselines)

- [ ] Add trajectory details to the `json_file` sink via `to_dict`.
- [ ] Add a trajectory summary to the `html_file` sink, preserving its pure-function-of-`RunResult`
      property.
- [ ] Add optional, one-directional trajectory export to the tracing integrations.
- [ ] `[P]` Regenerate `tests/public_surface_baseline.json`
      (`python tests/test_public_surface.py --update`).
- [ ] `[P]` Regenerate `tests/plugin_registry_baseline.json`
      (`python tests/test_plugin_registry_surface.py --update`).
- [ ] `[P]` Update `architecture.yaml` and regenerate `architecture.mmd`. Not conditional — verify
      the emitted edges even if none changed, since the manifest is the airgap's enforcement surface.
- [ ] Add CHANGELOG and user documentation.

## 6. Governance — PR 3

- [ ] `[P]` Claim the next free F-ID in `features.yaml` (F-051 at time of writing — re-verify) with
      `status: in_progress`, flipping to `done` with `implemented_in: <sha>` at land.
- [ ] `[P]` Add an executable `scripts/validations/F_0NN.py` proof following the `F_020.py` pattern.

## 7. Verification

- [ ] `./scripts/quality-gate.sh lint`
- [ ] `./scripts/quality-gate.sh typecheck`
- [ ] `./scripts/quality-gate.sh coverage` (96% floor)
- [ ] `python scripts/check_size_budget.py`
- [ ] `python scripts/check_charter_drift.py` and `check_charter_invariants.py`
- [ ] `python scripts/validate.py --tier fast`
- [ ] `make check-all`
- [ ] Read-only peer review recorded in `review.md`.

## Explicitly not in this change

Repeated execution, pass@k/pass^k, state adapters, judge bias probes, production ingestion. Each has
its own OpenSpec change.

# Changelog

All notable changes to `flow-corpus` are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the package follows semantic versioning. See the
repository root `CHANGELOG.md` for the cross-cutting feature narrative (F-011…F-015).

## [0.1.0] – 2026-06-20

### Added
- Specimen library (baseline control, MCTS, ReAct) behind a `Policy` seam with a seeded,
  offline `MockPolicy`; a self-contained specimen registry (no harness import).
- Deterministic SDLC task suite generator + committed snapshot; pure property oracle and a
  Cohen's-κ oracle-validation gate (co-determinate pairs only, power-aware).
- Version keyer (`hash(impl + agent_config)`; task and seed excluded) and corpus-owned
  deterministic `partition.bucket` for holdout/cross-check splits.
- Validation runner producing keyed `OutcomeRecord`s, Brier reliability (reused from
  `agent_core`'s Murphy decomposition), and AURC; single-authority holdout manager
  (instance- vs type-holdout) + rotation-stability; confidence cross-check with a seeded
  bootstrap-CI significance test; mutation engine for task-perturbation distributions.
- Discrimination canary (gold / no-op / random) with a Wilson-bounded pass-rate separation.
- Two-way version pin (`verify_pins`) against `flow_protocol` and `agent_core`.
- `CorpusConfig`: all thresholds config-driven with validation; derived `max_indeterminate_rate`.
- Structured logging + `debug_span` instrumentation across the runner, rotation, cross-check,
  κ-gate, pinning, and mutation engine (reuses `agent_core`'s public logging helpers).

### Notes
- Depends only on `pydantic>=2`, `flow-protocol`, and `agent-core` (public API) — never on
  `eval_harness`; the grimp drift gate enforces the airgap. 100% test coverage (gate ≥95),
  strict mypy, ruff clean, deterministic/offline, py3.10–3.12.

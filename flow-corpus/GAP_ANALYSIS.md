# Gap Analysis — flow-corpus

An honest account of what this package is, what it deliberately is not, and the residual
limitations of what it builds. Mirrors `agent-core/GAP_ANALYSIS.md` so every package in the
monorepo carries the same candour surface.

## 1. Built to production quality

The calibration corpus is real, tested logic: a specimen library (baseline / MCTS / ReAct behind
a `Policy` seam), a deterministic SDLC task-suite generator, property + Cohen's-κ oracles, a
single-authority holdout manager with rotation-stability, a confidence cross-check with a seeded
bootstrap-CI significance test, a mutation engine, and a validation runner emitting keyed
`OutcomeRecord`s. Measured baseline (2026-07): **100% branch coverage** against a ≥95% gate,
strict mypy (with the pydantic plugin), ruff clean, across Python 3.10–3.12. Structured logging
with `debug_span` instruments the runner, rotation, cross-check, κ-gate, pinning, and mutation
engine (reusing `agent_core`'s public logging helpers). All thresholds are config-driven on
`CorpusConfig` with validation; no literal appears in decision logic.

## 2. Reuse and airgap

Brier reliability is reused from `agent_core`'s Murphy decomposition rather than re-derived. The
package depends only on `pydantic>=2`, `flow-protocol`, and `agent-core`'s public API — never on
`eval_harness`. A two-way version pin (`verify_pins`) and the grimp drift gate enforce that
airgap and the acyclic dependency direction.

## 3. Deliberate design choices (not gaps)

- **Offline, seeded specimens.** The `MockPolicy` is deterministic and offline by design; the
  corpus exercises the *measurement* machinery, not live agents.
- **Power-aware oracle gating.** The κ-oracle gate only scores co-determinate pairs and is
  power-aware — a directional-only signal below the power floor cannot gate, by construction.
- **Corpus-owned partitioning.** `partition.bucket` is deterministic and owned here so holdout /
  cross-check splits are reproducible and independent of caller state.

## 4. Known limitations of what IS built

- The corpus is **synthetic**: it validates the statistical and holdout machinery end-to-end, not
  real agent trajectories. A real-transcript corpus bridge is out of scope for this package.
- Rotation-stability and cross-check significance are validated **within the seeded fixtures**;
  they characterise the method, not any particular production model.
- AURC / Brier reliability are only as meaningful as the (synthetic) outcome labels feeding them.

## 5. Coverage residual

Actual coverage meets or exceeds the 95% gate (100% at the 2026-07 baseline) with no source
omitted — the many small sub-package `__init__.py` markers inflate the file count but not the
measured logic.

## 6. Cross-reference

The repository-level measured baseline behind these numbers is recorded in
`docs/gap-analysis-2026-07.md`; the structural-budget enforcement that now guards this package
(complexity < 15, file ≤ 500 lines) is ADR 0019.

# Epic 1: Eval Matrix & Evaluation Reliability

## Focus Area
Core evaluation capabilities, trajectory evaluation, matrix coverage completeness, repeated-run reliability, and multi-judge consensus.

## Landed Features & Milestones
- **[x] Agent Trajectory Evaluation (F-051, ADR 0031)**: Deterministic normalization, structural immutability, canonical trajectory hash generation, O(n) loop detection, and trajectory scoring.
- **[x] Matrix Completeness & Freshness Gate (F-053, ADR 0032)**: Registry census + AST cell map + per-kind dim floors + `docs/matrix-coverage.md` freshness verification.
- **[x] Core Interfaces Protocol Migration**: All 6 core interfaces (`Scorer`, `Judge`, `DatasetSource`, `TargetRunner`, `ResultSink`, `StateAdapter`) declared as structural `typing.Protocol` with Python 3.11 floor (ADR 0034; `StateAdapter` added by F-060).
- **[x] Repeated-Run Reliability (F-056, `pass^k`)**: `run.repetitions` executes $k$ independent `target.run` invocations; `ReliabilityAggregator` computes `pass@k`/`pass^k` per item, never pooled; a `deterministic_sampling` diagnostic fires when a deterministic target makes variance structurally uninformative. Landed as PR #159 and PR #160 (merged 2026-08-18).
- **[x] Panel / Council Judge (F-059, `add-panel-judge`)**: Aggregates $N$ member judges under explicit strategies (`median`, `mean`, `majority`); surfaces per-member verdicts, disagreement spread, and inter-rater agreement ($\kappa$); `BudgetedJudge` charges `calls_per_evaluate` per member so an N-member panel is billed correctly, not under-charged by factor N. Landed as PR #162 (merged 2026-08-21).
- **[x] Judge Bias Probing & Calibration (F-057)**: Order-flip, verbosity-preference, and self-preference probes in `agent_core/judge_calibration.py`, isolated from `eval_harness` to preserve the `eval_harness ⇎ flow_corpus` airgap; `JudgeCalibrationReport.may_gate` blocks gating on an uncalibrated or biased judge. Landed as PR #160 (merged 2026-08-18).

## In Progress & Planned
1. **Stateful Outcome Evaluation (F-060, `add-stateful-outcome-evaluation`)**:
   - Implemented: `StateAdapter` protocol (`snapshot`/`evaluate`/`reset`) with the engine
     bracketing each attempt `reset → snapshot(before) → target.run → snapshot(after) →
     evaluate` under a lock; `state_transition`/`policy_violation` scorers; four local
     deterministic adapters (`in_memory`, `filesystem`, `sqlite`, `mock_http`).
   - Landed as PR #163 (merged 2026-08-21).

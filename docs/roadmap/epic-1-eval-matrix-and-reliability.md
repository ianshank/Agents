# Epic 1: Eval Matrix & Evaluation Reliability

## Focus Area
Core evaluation capabilities, trajectory evaluation, matrix coverage completeness, repeated-run reliability, and multi-judge consensus.

## Landed Features & Milestones
- **[x] Agent Trajectory Evaluation (F-051, ADR 0031)**: Deterministic normalization, structural immutability, canonical trajectory hash generation, O(n) loop detection, and trajectory scoring.
- **[x] Matrix Completeness & Freshness Gate (F-053, ADR 0032)**: Registry census + AST cell map + per-kind dim floors + `docs/matrix-coverage.md` freshness verification.
- **[x] Core Interfaces Protocol Migration**: All 5 core interfaces (`Scorer`, `Judge`, `DatasetSource`, `TargetRunner`, `ResultSink`) declared as structural `typing.Protocol` with Python 3.11 floor (ADR 0034).

## In Progress & Planned
1. **Repeated-Run Reliability (`pass^k`)**:
   - Execute $k$ independent `target.run` invocations.
   - Calculate binomial confidence intervals without synthetic variance injection.
   - Diagnostic warning when deterministic target configuration makes variance uninformative.
2. **Panel / Council Judge (PR #142, `add-panel-judge`)**:
   - Aggregate $N$ member judges under explicit strategies (`median`, `mean`, `majority`).
   - Surface per-member verdicts, disagreement spread, and inter-rater agreement ($\kappa$).
   - Multi-call budget accounting in `agent_core_adapter`.
3. **Stateful Outcome Evaluation**:
   - Sequential step evaluation with state-transition validation.
   - Attempt isolation and rollbacks for stateful environment targets.
4. **Judge Bias Probing & Calibration**:
   - Probe math isolated in `agent_core` to preserve the `eval_harness ⇎ flow_corpus` airgap.

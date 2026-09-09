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
- **[x] RCA evaluation matrix (F-067, ADR 0046)**: ranked diagnosis against a finite candidate set including correct abstention; `rca_maxz` baseline target; five scorers; frozen synthetic corpus at `corpora/rca/v1/`; advisory-only gate rules.
- **[x] Requirements-generation evaluation (F-068, ADR 0047)**: `provenance_recorder` target wrapper + `EvidenceStore` protocol; four deterministic scorers (`req_ac_recall`, `req_scope_hallucination`, `req_semantic_diversity`, `req_traceability_closure`); frozen synthetic corpus at `corpora/requirements/v1/`; advisory-only gate rules.
- **[x] Stateful Outcome Evaluation (F-060, `add-stateful-outcome-evaluation`)**: `StateAdapter` protocol (`snapshot`/`evaluate`/`reset`) with the engine bracketing each attempt `reset → snapshot(before) → target.run → snapshot(after) → evaluate` under a lock; `state_transition`/`policy_violation` scorers; four local deterministic adapters (`in_memory`, `filesystem`, `sqlite`, `mock_http`). Landed as PR #163 (merged 2026-08-21).
- **[x] Agent-in-the-loop test generation (F-069, ADR 0048, Deck B / B5)**: registered `testgen_agent` pipeline: generate from focal+obligations (never sees `inputs.suite`), then `run_generated_suite` in-process. F-065 scorers unchanged. Quote thorough holdout n=11 unique; do not quote `pass^k` from a deterministic fake.
- **[x] Eval-evidence Phase 8 residual**: Provenance SHA reachable (ancestor of HEAD) plus monotonicity/waiver; ADR 0033 amendment.
- **[x] Eval-evidence Phase 9 fleet census + Phase 10 M2/M6 canaries**: `tests/_fleet_matrix.py`; no fabricated `MATRIX_KIND` floors on sibling packages.

## In Progress & Planned

### Human-critical path (agents must not substitute)

1. **Enable branch protection on `main`** after ADR 0037's five-green soak.
   Use `docs/runbooks/branch-protection-enablement.md`. Do **not** `--apply`
   from an agent session; do **not** require CODEOWNERS; leave `merge-gate-data`
   unprotected.
2. **Weekly HUMAN_AUDIT** via `merge-gate-audit.yml` / `merge-gate-verdict.yml`
   only. Agents must not write the live store or fabricate `provenance=human`.
3. **Golden corpus** floor 50, two annotators, κ ≥ 0.60
   (`docs/golden-corpus/`). Engineering scaffolding exists; labeling is human.

### Agent follow-ons (not this ranking)

1. **Do not implement** measurement-wedge WS-1 or the production eval flywheel
   until `docs/plans/vp-strategic-deep-dive/DECISIONS.md` §5 is decided.
2. **After a full e2e `--update`**: drop `PROVENANCE_SHA_WAIVERS` /
   `MONOTONICITY_WAIVERS` rows that the restamp retires.
3. **Fail-closed pip-audit** only once the tree is pinned *and* CHARTER-named
   Snyk Code (or an explicit CHARTER amendment) owns the gate.

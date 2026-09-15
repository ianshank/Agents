# 0049 — Fixture replay target: envelope reload, exact re-score, counterfactual TargetRunner

- Status: **Accepted.**
- Date: 2026-09-14
- Related: `openspec/changes/add-fixture-replay/`, F-070, F-051 / ADR 0031, ADR 0046
  (counterfactual is not a Scorer).
- Amends CHARTER? **No.** Does not expand §3. Does not authorize the production-eval flywheel
  (`openspec/changes/add-production-eval-flywheel/`) or F-036.

## Context

F-051 made target-owned `AgentTrajectory` values scoreable, but export was one-way:
`trajectory_to_dict` existed and `trajectory_from_dict` did not. There was no CLI to
re-score a recorded run, and ADR 0046 forbade a `counterfactual_support` **scorer**
because a scorer cannot re-execute. Reviewers still could not hold retrieval
observations fixed while swapping one stub, or point at the first `tool_error` when a
global pass-rate looked flat.

That is a **fixture replay** gap, not a missing observability platform. CHARTER §3
lists a general observability platform as a non-goal. Langfuse / Phoenix / BrainTrust
remain optional sinks and UIs.

## Decision

1. **Envelope.** A frozen `ReplayEnvelope` wraps `AgentTrajectory` plus slice tags,
   payload hashes, and optional `StateSnapshot` refs. Envelope schema version
   (`1.0.0`) is independent of config `SCHEMA_VERSION` and of
   `TRAJECTORY_SCHEMA_VERSION`.
2. **`trajectory_from_dict`** is the strict inverse of `trajectory_to_dict`. Unknown
   keys raise. Round-trip is a test, not a comment.
3. **Exact replay** re-emits recorded outputs and trajectories. No live tools, no
   vendor span fetch. The engine still never reconstructs trajectories from
   Langfuse/Phoenix spans.
4. **Counterfactual replay** is a registered `TargetRunner` (`replay`) whose
   `run(item)` consults a pinned envelope and a single override map. Mode and
   overrides live on the constructor / `target.params` — `run` still takes only
   `item` (REVIEW.md §B14). It is not a scorer.
5. **Archive** is append-only JSONL. Writes are confined by `OUTPUT_ROOT`; reads by
   `DATA_ROOT`, via `core._paths.resolve_confined_path`.
6. **Slice tags** on the envelope are the grouping key for pass-rate deltas. This
   does not grow `comparison.py` (ADR 0019 ceiling).
7. **SQL / ClickHouse / production ingest** are out of this ADR. Optional sketches
   live under `experiments/trace-analytics/` (unsigned, not in `make check-all`).

## Consequences

- New `eval_harness.replay` component and `architecture.yaml` edges
  (`replay → core, plugins`; `plugins → replay`; `cli → replay`).
- CLI subcommand `eval-harness replay` dispatched from `cli.py` without growing
  `engine.py` / `comparison.py` past 500 lines.
- Matrix rows for target `replay` (dims 1, 2, 3, 6).
- Demo beat 6 uses committed fixtures only (F-006: gates never live-eval).
- `features.yaml` F-070 + `scripts/validations/F_070.py`.

## Alternatives considered

- **Counterfactual as a scorer.** Rejected — ADR 0046: immutable snapshots have no
  world to replay; a scorer cannot be the execution seam.
- **Reconstructing trajectories from Langfuse/Phoenix spans.** Rejected — CHARTER
  offline suite + F-051 contract ("the harness never reconstructs a trajectory from
  tracing spans").
- **ClickHouse (or DuckDB) inside `eval_harness`.** Rejected — CHARTER §3
  observability-platform non-goal; Change 5 remains blocked.
- **Carrying replay state in reserved `TargetOutput.metadata` keys.** Rejected —
  same reason ADR 0031 rejected that for trajectory; the envelope is an explicit type.
- **Growing `engine.py` / `comparison.py` in place.** Rejected — ADR 0019 hard
  ≤500 lines.

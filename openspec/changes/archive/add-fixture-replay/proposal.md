# Change: add-fixture-replay

**Status:** implemented (archived; landed `e1c8e970`) 
**Date:** 2026-09-14
**Depends on:** F-051 `AgentTrajectory`, ADR 0031, ADR 0046 (counterfactual is a TargetRunner, not a Scorer)
**Does not depend on / must not unblock:** `openspec/changes/add-production-eval-flywheel` (CHARTER-blocked)

## Why

The harness already scores target-owned trajectories and exports a one-line tool path in HTML. Reviewers still cannot:

1. Reload a recorded run and re-score it (`trajectory_from_dict` did not exist).
2. Hold tool/retrieval observations fixed while swapping one variable (prompt stub, tool stub).
3. Point at the first `tool_error` step as the diagnosis, rather than a scalar pass-rate.

That is a **fixture replay** gap, not a missing observability platform.

## Why this is in CHARTER §3

In scope: new registered `TargetRunner` + JSONL archive + CLI subcommand. Offline, deterministic, no network.

Out of scope: production ingestion, redaction queues, ClickHouse, reconstructing trajectories from Langfuse/Phoenix spans, live/shadow replay against real dependencies.

## What changes

- Versioned **envelope** wrapping existing `AgentTrajectory`. Independent of config `SCHEMA_VERSION`.
- `trajectory_from_dict` inverse of `trajectory_to_dict`, strict unknown keys.
- Append-only JSONL archive under `OUTPUT_ROOT` (same confinement as sinks).
- Registered target `replay` with modes `exact` | `counterfactual`.
- CLI `eval-harness replay` implemented in `eval_harness.replay.cli` and dispatched from `cli.py` without growing `engine.py` / `comparison.py`.
- Demo beat: envelopes tagged `freshness=normal|sensitive`, global pass-rate can stay non-zero while the sensitive slice drops, first `tool_error` printed as an ordered step list.

## Non-goals

- ClickHouse / DuckDB as a runtime dependency of the offline suite.
- `counterfactual_support` scorer (ADR 0046).
- Span reconstruction from vendor OTel/Langfuse.
- Unblocking `add-production-eval-flywheel` or F-036.
- Mango/planlint.

## ADR

**0049** (`docs/decisions/0049-fixture-replay-target.md`). 0007 remains an intentional gap.

## Compile-down

`docs/plans/fixture-replay/PLAN.md` + F-070 + ADR 0049.

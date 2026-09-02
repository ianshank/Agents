# Change: add-stateful-outcome-evaluation

**Status:** implemented (archived; landed `b709ae1`) · **Date:** 2026-08-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/agent-eval-coverage/REVIEW.md`
**Authorised by:** [ADR 0031](../../../docs/decisions/0031-additive-core-model-extension-for-agent-evaluation.md)
**Depends on:** `add-repeat-reliability-metrics` (reset/isolation is defined per attempt)
**Compiles down to:** `docs/plans/agent-eval-coverage/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

Every built-in scorer reads `output.output` — the agent's own account of what it did. An agent that
replies "the booking was completed" while creating no booking scores identically to one that
actually created it. This is the failure mode that catches the agent which says it completed work
and did not change the world, and no scorer in the tree can currently detect it.

## What changes

- Add a `StateAdapter` Protocol with `snapshot`, `evaluate` and `reset`, and a registry for it,
  following the five existing component registries.
- Capture before/after state around each attempt in the **engine**.
- Add a deterministic state scorer asserting the observed transition against a declared expectation.
- Add a policy-violation scorer that fails independently of goal success.
- Ship local deterministic adapters only: in-memory mapping, filesystem sandbox, SQLite transaction,
  mock HTTP service.

## Scope / non-goals

- **Non-goal: production database credentials or domain-specific adapters.** The first change ships
  the contract and local adapters. Domain validators are later work behind the same seam.
- **Non-goal: runtime guardrails.** Evaluation is offline or asynchronous; guardrails enforce at
  request time. Out of charter scope.
- **Non-goal: network I/O on the offline path.** The mock HTTP adapter is in-process.

## Impact

- **Engine lifecycle change** under ADR 0031: snapshot → run → snapshot → evaluate → reset.
- New component in `architecture.yaml` with declared edges; the manifest is a protected path.
- **Protected paths:** `src/eval_harness/scorers/**`, `config/**`, `tests/**`, `features.yaml`,
  `scripts/validations/**`, `architecture.yaml`.

## Two corrections against the externally proposed version

**`EvalContext` does not exist.** The proposed `StateAdapter` protocol was typed against it; the
per-run context type is `RunContext` (`core/types.py:110`).

**The runner cannot own state capture.** `TargetRunner.run(self, item)` takes no context parameter
(`core/interfaces.py:52-56`), so there is nowhere on the target to hang before/after capture. The
engine owns the lifecycle. This also keeps I/O in a narrow seam and leaves scorers pure per-item
maps, as CHARTER §4 invariant 4 requires (`REVIEW.md` §B4).

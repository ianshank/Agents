# Change: add-agent-trajectory-evaluation

**Status:** landed — F-051 @ `a5e1a7847f` · **Date:** 2026-08-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/agent-eval-coverage/REVIEW.md` (peer review of an external coverage
analysis and its proposed implementation plan)
**Authorised by:** [ADR 0031](../../../../docs/decisions/0031-additive-core-model-extension-for-agent-evaluation.md)
**Compiles down to:** `docs/plans/agent-eval-coverage/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

The harness evaluates `TargetOutput` as an output artifact. It cannot represent or score the
sequence of tool calls, observations, errors and recovery actions that produced that output. A
target may therefore return plausible text while taking an invalid, wasteful, looping or
policy-violating execution path, and every built-in scorer will grade it a pass — all seven read
`output.output` only (`src/eval_harness/scorers/__init__.py`).

Langfuse tracing exists, but tracing is not scoring: spans are exported for human inspection and
never enter a verdict. The gap was confirmed against the tree — `grep -ril trajectory` matches one
file, a synthetic confidence flow shape in `flow-corpus` carrying no tool calls.

## What changes

- Add immutable `ToolCallRecord`, `TrajectoryStep` and `AgentTrajectory` value objects to
  `eval_harness.core.types`.
- Append an optional `trajectory` field to `TargetOutput` as its **last** field.
- Add a pure normalisation module `eval_harness.core._trajectory` (tool-name canonicalisation,
  recursive argument canonicalisation with stable key ordering, configurable ignored-field set).
- Register four matching scorers — `trajectory_exact`, `trajectory_in_order`,
  `trajectory_any_order`, `trajectory_precision_recall` — in a new `scorers/trajectory.py`.
- Register three quality scorers evaluated independently of any reference:
  `trajectory_step_efficiency`, `trajectory_loop_detection`, `trajectory_recovery`.
- Surface trajectories in the `json_file` and `html_file` sinks.

## Scope / non-goals

- **Non-goal: repeated execution or pass@k/pass^k.** That is `add-repeat-reliability-metrics`.
- **Non-goal: external-state adapters.** That is `add-stateful-outcome-evaluation`.
- **Non-goal: runtime guardrails.** Out of charter scope entirely.
- **Non-goal: any change to existing LLM-judge behaviour.**
- **Non-goal: requiring targets to emit a trajectory.** Text-only targets stay first-class; the
  built-in `echo` and `callable` targets are unchanged.
- **Non-goal: making Langfuse the canonical trajectory representation.** Capture is target-owned;
  Langfuse stays an export sink.

## Impact

- **Additive core-model change** under ADR 0031's six obligations — append-only field, no freezing,
  `SCHEMA_VERSION` untouched, `to_dict()` omits the key when absent, baselines regenerated,
  default-off.
- **Protected paths:** `src/eval_harness/scorers/**`, `tests/**`, `features.yaml`,
  `scripts/validations/**`, and `architecture.yaml` if component edges change. Each needs the
  `eval-change-approved` label plus CODEOWNERS review, split into its own PR.
- New F-ID claimed at land with an executable `scripts/validations/F_0NN.py` proof.
- Architecture manifest and CHANGELOG updated; user documentation added.

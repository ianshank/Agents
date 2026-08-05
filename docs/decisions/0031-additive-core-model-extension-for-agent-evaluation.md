# 0031 - Agent evaluation may extend the core models and the engine loop, additively and under compatibility obligations

**Status**: Proposed
**Date**: 2026-08-05

Related: [ADR 0005](0005-calibrated-merge-gate.md), [ADR 0011](0011-multi-model-comparison.md),
[ADR 0013](0013-model-backed-target.md) (the additive-opt-in pattern this follows),
[CHARTER.md](../CHARTER.md) §4 invariant 1 (the constraint being amended),
`docs/plans/agent-eval-coverage/REVIEW.md` (the peer review that motivates this),
`openspec/changes/add-agent-trajectory-evaluation/`.

## Context and Problem Statement

The harness evaluates a `TargetOutput` as an output artifact. It cannot represent or score the
sequence of tool calls, observations, errors and recovery actions that produced that output, cannot
run an item more than once, and cannot assert on environment state. A target may therefore return
plausible text while taking an invalid, wasteful, looping or policy-violating execution path, and
the harness will score it as a pass. An independent coverage review confirmed all three gaps
against the tree (`docs/plans/agent-eval-coverage/REVIEW.md` §A8).

Closing them runs into [CHARTER.md](../CHARTER.md) §4 invariant 1:

> **Open/closed extensibility.** New judges, scorers, sinks, datasets, and targets are added through
> registries / the `eval_harness.plugins` entry-point group; the engine, core models, and
> registries themselves stay unmodified.

Trajectory evaluation needs a trajectory to live somewhere on the target's result — a **core model**.
Repeated-run reliability needs the item loop to execute an item k times — the **engine**. Charter §6
requires that a change which would violate an invariant be surfaced for human decision rather than
implemented, which is what this ADR does.

The alternative considered and rejected was carrying the trajectory inside the existing
`TargetOutput.metadata` dict under a reserved key. That preserves the letter of the invariant while
losing every property the invariant exists to protect: no type checking, no `mypy` surface, no
public-API guard coverage, and a reserved-key convention that any plugin can silently collide with.
It also does not help at all with repeated runs, which require an engine change regardless. Buying a
formally-clean invariant at the price of an untyped magic key is a worse outcome than amending the
invariant deliberately.

## Decision

The invariant is amended, narrowly: **`eval_harness` core models and the engine execution loop may
be extended for agent evaluation, additively, subject to the obligations below.** The open/closed
rule is otherwise unchanged — trajectory scorers, state adapters and reliability metrics are still
registered components, and the registries themselves stay unmodified.

Every change made under this ADR carries these obligations:

1. **Append-only fields.** New dataclass fields are appended last with a default. No existing field
   is reordered, renamed, retyped or removed. Positional construction of every existing type keeps
   working, and a regression test asserts it.
2. **No freezing of existing types.** `TargetOutput` stays a mutable dataclass. New value objects
   (`ToolCallRecord`, `TrajectoryStep`, `AgentTrajectory`) are `frozen=True`.
3. **`SCHEMA_VERSION` is untouched.** All config additions are optional with defaults that reproduce
   current behaviour, so old configs parse unmodified — consistent with charter §3's exclusion of
   `SCHEMA_VERSION` bumps from feature branches.
4. **Serialisation stays backward compatible.** `RunResult.to_dict()` omits new keys when the
   underlying value is absent, so historical result JSON is byte-identical.
5. **Surface baselines are regenerated in the same change.** `tests/public_surface_baseline.json`
   and `tests/plugin_registry_baseline.json` diff only by the intended additions (F-039).
6. **Default-off behaviour.** A target that emits no trajectory, a config that requests no
   repetitions, and an item that declares no state adapter all behave exactly as before.

### The airgap is not amended

`architecture.yaml` declares that `eval_harness` never depends on `flow_corpus` and
`behavioral_regression` never depends on `eval_harness` (F-011, negative test F-012). Judge
bias-calibration work needs the κ and statistical-power machinery that currently lives in
`flow_corpus`/`behavioral_regression`, on the far side of that boundary.

**That boundary holds.** Shared calibration math is placed in `agent_core` — dependency-free and
already importable by both sides — and consumed by `eval_harness` through the existing declared edge
`agent_core_adapter: [agent_core, config, core]`. No new component edge is declared, and
`architecture.yaml` is not edited to permit one. `agent_core` remains config-file-free: the probe
tunables are frozen dataclass fields, not YAML knobs.

## Consequences

- **Positive.** Trajectory, reliability and state evaluation become typed, `mypy`-checked, guarded by
  the public-surface baseline, and visible in the result schema — none of which the metadata-key
  workaround would have provided.
- **Positive.** The amendment is bounded and written down. Future core-model changes still require
  their own escalation; this ADR authorises agent-evaluation extensions, not a general licence.
- **Negative.** `docs/CHARTER.md` §4 invariant 1 is no longer literally true of the core models, and
  its wording must be updated to reference this ADR. Reviewers lose a bright-line rule and gain a
  rule with a documented exception, which is harder to apply mechanically.
- **Negative.** The engine's item loop becomes more complex once attempts exist. The mitigation is
  that attempt expansion stays inside the run loop and aggregation stays a pure function over
  persisted raw attempts, so the added complexity is testable in isolation.
- **Neutral.** No behaviour changes for any existing configuration until a target opts in by
  emitting a trajectory or an operator opts in by configuring repetitions or a state adapter.

## Compliance

Enforced by the existing gates rather than by review alone: `tests/test_backwards_compat_config.py`
and `tests/test_backwards_compat_cli.py` (obligation 1), `tests/test_public_surface.py` and
`tests/test_plugin_registry_surface.py` (obligation 5), `scripts/check_charter_invariants.py` and
`scripts/check_charter_drift.py` (the amended charter text), and the architecture drift-guard (the
airgap).

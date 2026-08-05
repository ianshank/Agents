# Change: extend-judge-calibration

**Status:** proposed · **Date:** 2026-08-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/agent-eval-coverage/REVIEW.md`
**Compiles down to:** `docs/plans/agent-eval-coverage/PLAN.md` + F-IDs (claimed at land).

## Why

The external coverage analysis graded judge calibration "Not Covered". That is refuted: this
repository already ships Cohen's κ with a statistical-power floor
(`flow-corpus/flow_corpus/oracles/kappa_gate.py`), judge-versus-human validation returning a
`may_gate` trust signal (`behavioral-regression/.../oracle.py::validate_judge`), held-out split
discipline enforced in code (`agent_core/golden.py`), and a full calibration report with ECE, the
Brier decomposition, AUROC and Wilson CIs (F-043).

What is genuinely missing is narrower and real: **bias probes**. An LLM judge can clear κ against a
human label set while still preferring whichever answer it sees first, whichever is longer, or
whichever its own model family produced. Agreement alone does not detect any of the three.

## What changes

- Add order-bias, verbosity-sensitivity and self-preference probe math to `agent_core`.
- Add a pairwise, order-swapped calibration corpus type.
- Extend the existing calibration report with order-flip rate, verbosity preference delta and
  judge-family metadata.
- Require a named calibration artifact ID before a judge may gate.

## Scope / non-goals

- **Non-goal: a second calibration system.** κ, power floors, held-out splits and advisory-only
  behaviour already exist and are extended, not replaced.
- **Non-goal: YAML knobs in `agent_core`.** It is deliberately config-file-free
  (`openspec/project.md`); probe tunables are frozen dataclass fields.
- **Non-goal: amending the airgap.** See below.

## Where the code goes, and why it is not obvious

The κ machinery lives in `flow_corpus` and `behavioral_regression`. The judges that gate live in
`eval_harness`. `architecture.yaml` severs those two sides: `eval_harness` never imports
`flow_corpus` and `behavioral_regression` never imports `eval_harness` — F-011's structural airgap,
with F-012's forced-mismatch negative test, and `architecture.yaml` itself is protected precisely so
that edge changes get human review.

The externally proposed instruction to "extend those mechanisms" therefore had no legal
implementation. The resolution ([ADR 0031](../../../docs/decisions/0031-additive-core-model-extension-for-agent-evaluation.md)):
**shared probe math goes in `agent_core`** — dependency-free and already importable by both sides —
and `eval_harness` consumes it through the existing declared edge
`agent_core_adapter: [agent_core, config, core]`. No new component edge, no manifest edit, one
calibration system (`REVIEW.md` §B5).

## Impact

- New module in `agent-core/agent_core/` at the **95%** coverage floor.
- Consumption seam in `src/eval_harness/agent_core_adapter/`.
- **Protected paths:** `src/eval_harness/judges/**` if gating behaviour changes, `tests/**`,
  `features.yaml`, `scripts/validations/**`.

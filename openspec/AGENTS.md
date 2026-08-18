# OpenSpec — fleet coordination contract

How the agent/sub-agent fleet drives an OpenSpec change through to the enforced back-end.
This is the concrete "using all agents and sub-agents" mapping. Fleet members are used in
their **native roles**, with one stated exception: `spec-guardian` and `peer-reviewer` are
new `claude-foundation/agents/` charters that `add-foundation-reviewer-charters` adds to the
fleet, filling the `review` role between `verify` and `archive` that no existing member
held — a read-only conformance gate, then a read-only adversarial second pass. Every other
row invents nothing.

## Lifecycle → owner mapping

| OpenSpec phase | Repo compile-down target | Primary owner (fleet / sub-agent) | Review / gate |
|---|---|---|---|
| `propose` (proposal.md) | `docs/plans/<topic>/PLAN.md` | `foundation:plan` skill | human sign-off |
| `design` (design.md) | a numbered ADR `docs/decisions/NNNN-*.md` | **Plan** sub-agent | human (ADR accept) |
| spec delta (`specs/<cap>/spec.md`) | `features.yaml` F-ID rows + `verification` bullets | **general-purpose** sub-agent | `eval-change-approved` label |
| each scenario | `scripts/validations/F_0NN.py` proof | `foundation:test-first` | `scripts/validate.py` in CI |
| `apply` (implement tasks) | source under `agent-core/agent_core/` etc. | **general-purpose** sub-agent | `foundation:code-review` (forked, read-only) |
| verify | `make -C <pkg> check` (coverage floor) | `test-runner` sub-agent | package CI |
| `review` (conformance pass, new) | `openspec/changes/<id>/review.md` — verdict + numbered findings | `spec-guardian` sub-agent | advisory — a `tasks.md` checklist item, never CI-blocking |
| `review` (adversarial pass, new) | `openspec/changes/<id>/review.md` — two-pass fact-check + attack section; persists into `changes/archive/<id>/review.md` | `peer-reviewer` sub-agent | advisory — a `tasks.md` checklist item, never CI-blocking |
| `archive` | `features.yaml` `status: done` + `implemented_in:<sha>` | **general-purpose** sub-agent | `quality-gates.yml` |

**Staging precondition** (stated, not assumed): every fleet member sourced from
`claude-foundation/` above — the three `foundation:*` skills, plus `test-runner`,
`spec-guardian`, and `peer-reviewer` — comes from a plugin that is staged in-tree, not
installed, in this repo's own sessions (ADR 0028). Dispatching any of them here requires a
session started with `claude --plugin-dir claude-foundation`; absent that, the corresponding
row degrades to a `general-purpose` sub-agent inlining the same method — Phase 5
(`add-openspec-implementation-review`, `docs/plans/orbital-drift-alignment/PLAN.md`) is
required to do exactly this for `review` rather than silently failing to find the agents.

## Always-on guards (run under every agent action)

- `foundation:pre-tool-guard` — fail-closed: denies secret-file reads/writes, confines
  writes to project + scratch.
- `foundation:post-edit-verify` — advisory lint feedback on each edited file.
- `foundation:session-logger` — privacy-conscious JSONL audit of each tool call.
- `architecture-drift-guard` — blocks undeclared import edges vs `architecture.yaml`.

## Measurement fleet (consulted by data-gathering changes)

- `eval_harness` judges (`anthropic`, `openai`, `bedrock`, `phoenix_evals`, `mock`) +
  `scorers.llm_judge` + the `model-bench` skill — the LLM-as-judge proxy machinery.
- `behavioral-regression` `SyntheticJudge` / `RegressionDetector` / `decide_ship` — an
  independent judge + drift gate.
- `flow-corpus` κ-validated oracles — offline ground-truth for calibration corpora.
- `dataset-lint` / `eval-corpus-forge` — validate/assemble any eval fixtures a change adds.

## The subject vs the executors

The `agent-core` runtime (`LoopController` / `AsyncLoopController` / `ParallelClaimRunner`),
the calibrated merge gate (`merge_gate.decide()`, `merge_gate_ci`), and the
`(agent_version, domain)` calibration cells are the **subject** that changes measure and
tune — not executors. Do not route change-execution through them.

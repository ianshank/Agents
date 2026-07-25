# OpenSpec — fleet coordination contract

How the agent/sub-agent fleet drives an OpenSpec change through to the enforced back-end.
This is the concrete "using all agents and sub-agents" mapping. Fleet members are used in
their **native roles**; nothing here invents a new agent.

## Lifecycle → owner mapping

| OpenSpec phase | Repo compile-down target | Primary owner (fleet / sub-agent) | Review / gate |
|---|---|---|---|
| `propose` (proposal.md) | `docs/plans/<topic>/PLAN.md` | `foundation:plan` skill | human sign-off |
| `design` (design.md) | a numbered ADR `docs/decisions/NNNN-*.md` | **Plan** sub-agent | human (ADR accept) |
| spec delta (`specs/<cap>/spec.md`) | `features.yaml` F-ID rows + `verification` bullets | **general-purpose** sub-agent | `eval-change-approved` label |
| each scenario | `scripts/validations/F_0NN.py` proof | `foundation:test-first` | `scripts/validate.py` in CI |
| `apply` (implement tasks) | source under `agent-core/agent_core/` etc. | **general-purpose** sub-agent | `foundation:code-review` (forked, read-only) |
| verify | `make -C <pkg> check` (coverage floor) | `test-runner` sub-agent | package CI |
| `archive` | `features.yaml` `status: done` + `implemented_in:<sha>` | **general-purpose** sub-agent | `quality-gates.yml` |

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

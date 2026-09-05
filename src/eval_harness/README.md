# eval_harness

This directory is the source of **`langfuse-eval-harness`**, the flagship package
of the monorepo — a dynamic, modular, backwards-compatible enterprise **LLM
evaluation harness** with first-class Langfuse integration and SDK-optional seams
for Phoenix and BrainTrust.

> **The authoritative guide is the repository [README](../../README.md).** This
> file is a short orientation for anyone browsing `src/`.

## Sub-package map

| Package | What it holds |
|---|---|
| `config/` | versioned config models, migrations, env-interpolating loader |
| `core/` | types, interfaces (abstract base classes), the generic `Registry`; `_imports.py`/`_paths.py` are the operator-controlled trust-boundary gates config-driven imports and paths route through — see [Config files are executable input](../../README.md#config-files-are-executable-input) |
| `scorers/` | exact_match, regex_match, contains, json_keys, llm_judge, weighted, autoevals; `trajectory.py` adds trajectory_exact, trajectory_in_order, trajectory_any_order, trajectory_precision_recall, trajectory_step_efficiency, trajectory_loop_detection, trajectory_recovery (F-051 — see [docs/agent-trajectory-evaluation.md](../../docs/agent-trajectory-evaluation.md)); `state.py` adds state_transition, policy_violation (F-060, read the engine's per-attempt StateEvaluation) |
| `datasets/` | inline, jsonl, langfuse, braintrust, csv, parquet — file-backed sources confined by `DATA_ROOT` |
| `targets/` | echo, callable (dynamic import — gated by `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST`, unset denies), model (alias llm) |
| `sinks/` | console, json_file, html_file, langfuse, phoenix, braintrust — file-backed sinks confined by `OUTPUT_ROOT` |
| `judges/` | mock, openai (Nemotron/GPT), anthropic, bedrock, phoenix_evals, panel (aggregates N member judges — see `judges/panel.py`) |
| `state_adapters/` | in_memory, filesystem, sqlite, mock_http (F-060) — deterministic local adapters the engine snapshots around `target.run` when `state_adapter` is configured |
| `langfuse_client/`, `phoenix_client/`, `braintrust_client/` | SDK-optional tracing/export seams |
| `agent_core_adapter/` | bridge to `agent-core` (budget ledger, calibration surface, BudgetedJudge cost-cap wrapper) |
| `gating/` | the config-driven quality gate. Its verdict is attached to `RunResult.gate` **before** the sinks emit, so every exported artifact carries it (F-062). A rule marked `report_only: true` is evaluated on the identical path and filed to an advisory channel instead of failing the run — use it to soak an uncalibrated threshold inside a gate whose other rules stay live |
| `engine.py`, `cli.py` | orchestration and the `eval-harness` entry point |

## Extending without touching core

Components self-register in `Registry` objects and are built by name at runtime;
third parties add components via the `eval_harness.plugins` entry-point group. See
[Extend (no core changes)](../../README.md#extend-no-core-changes) in the root
README for a worked example.

## Note on protected paths

`gating/`, `scorers/`, and `judges/` are **protected** — changes there require the
`eval-change-approved` label (see
[CONTRIBUTING.md](../../CONTRIBUTING.md#protected-paths-require-a-labeled-approval)).

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
| `core/` | types, interfaces (abstract base classes), the generic `Registry` |
| `scorers/` | exact_match, regex_match, contains, json_keys, llm_judge, weighted, autoevals |
| `datasets/` | inline, jsonl, langfuse, braintrust, csv, parquet |
| `targets/` | echo, callable (dynamic import) |
| `sinks/` | console, json_file, html_file, langfuse, phoenix, braintrust |
| `judges/` | mock, openai (Nemotron/GPT), anthropic, bedrock, phoenix_evals, budgeted |
| `langfuse_client/`, `phoenix_client/`, `braintrust_client/` | SDK-optional tracing/export seams |
| `agent_core_adapter/` | bridge to `agent-core` (budget ledger, calibration surface) |
| `gating/` | the config-driven quality gate |
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

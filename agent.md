# Langfuse Eval Harness - Agent Guide

This document outlines how AI agents interact with and utilize the `langfuse-eval-harness` to evaluate code, models, and workflows.

## Harness Overview
The `langfuse-eval-harness` is a modular, config-driven engine for running evaluations across various datasets and models, with deep integration into Langfuse for observability. 

It provides:
- **Pluggable Architecture**: Configurable through `yaml` files and entry points.
- **Multiple LLM Backends**: Supports Anthropic, Bedrock, and OpenAI compatible judges.
- **Data Ingestion**: Processes data from CSV, Parquet, JSONL, and inline formats.

## Key Components for Agents

### 1. Run Config
Evaluations are run using `EvalConfig` which dictates:
- `dataset`: Which dataset format (csv, parquet, jsonl, etc.) and where it's loaded from.
- `target`: The callable or script to execute.
- `scorers`: The list of metrics to gather (e.g., exact_match, llm_judge).

### 2. LLM Judges
When evaluations require semantic checks, LLM judges are utilized.
- **AnthropicJudge**: Evaluates output using Claude models.
- **BedrockJudge**: Hardened for robust integration with AWS Bedrock.
- **OpenAIJudge**: Utilizes Nemotron/GPT models.

### 3. Execution
Agents can invoke the evaluation harness through its CLI:
```bash
eval-harness run --config config/eval.yaml
```

Or using the specialized `skills` directory for targeted tasks, such as `skills/openai-judge/scripts/run.py` offering options like `--judge-type`.

## Eval Integrity
Agents should be aware of the robust gating mechanisms:
- **Regression Gate**: `scripts/regression_gate.py` fails on net-new lint/test issues.
- **Protected Path Guard**: Changing evaluation components requires human review.

*When updating the harness, ensure test coverage stays at 100%.*

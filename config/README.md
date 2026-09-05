# config/

Declarative configuration consumed by the harness and its gates. **This directory
is a protected path** (`scripts/eval_protected_paths.py` + `.github/CODEOWNERS`):
changes require a CODEOWNER review and the `eval-change-approved` label, because
these files can alter what the evaluation measures.

| File | Purpose | Consumed by |
|---|---|---|
| `eval.example.yaml` | The canonical example eval configuration (offline-runnable). | `eval-harness run --config config/eval.example.yaml` |
| `nemotron_eval.yaml` | Eval config targeting the NVIDIA Nemotron judge. | `eval-harness run` (needs `NVIDIA_API_KEY`) |
| `lm_studio_eval.yaml` | Eval config targeting a local LM Studio (OpenAI-compatible) endpoint. | `eval-harness run` |
| `model_target.yaml` | Real model-backed target configuration (ADR 0013). | the model-backed target |
| `merge-gate-domains.yaml` | Domain definitions for the calibrated merge gate. | `agent_core` merge-gate / `scripts/merge_gate_context.py` |
| `agent-authors.yaml` | Agent identification for merge-gate seed routing (ADR 0023, F-042) — head-ref prefixes → `agent_version`. | `scripts/merge_gate_context.py`, `scripts/agent_confidence.py` |
| `agent-confidence.yaml` | Parameters for the deterministic agent-confidence proxy (F-042, F-061). | `scripts/agent_confidence.py` |
| `testgen_eval.yaml` | Test-generation evaluation over the shipped corpus (F-065, ADR 0043). Every gate rule is advisory. | `eval-harness run` with `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=eval_harness.targets.testgen` |
| `trajectory_eval.yaml` | Agent-trajectory evaluation example (F-051, ADR 0031). | `eval-harness run` with `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=tests` |
| `legacy.v0_9.yaml` | A legacy (v0.9) config kept to exercise the migration chain. | config migration tests |

Credentials are **never** stored here — they come from environment variables
(see [`../.env.example`](../.env.example)). Every numeric threshold lives in a
validated config field, not a literal at a call site (see
[`../AGENTS.md`](../AGENTS.md#non-negotiable-constraints)).

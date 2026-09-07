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
| `rca_eval.yaml` | RCA evaluation over the shipped corpus (F-067, ADR 0046). Every gate rule is advisory. | `eval-harness run --config config/rca_eval.yaml` |
| `requirements_eval.yaml` | Requirements-generation evaluation over the shipped corpus (F-068, ADR 0047). Every gate rule is advisory. | `eval-harness run --config config/requirements_eval.yaml` |
| `trajectory_eval.yaml` | Agent-trajectory evaluation example (F-051, ADR 0031). | `eval-harness run` with `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=tests` **and `PYTHONPATH=.`** — its target lives in `tests/_sut.py`, which only pytest puts on the path |
| `legacy.v0_9.yaml` | A legacy (v0.9) config kept to exercise the migration chain. | config migration tests |

Every config listed above is either exercised end to end by
`tests/integration/test_pipeline_e2e.py::test_a_shipped_offline_config_runs_end_to_end`
or named in that module's exclusion set with a reason. A config that is neither fails
`test_every_shipped_config_is_either_journeyed_or_explicitly_excluded`, so a new one
cannot ship unrun — the gap that let `requirements_eval.yaml` land naming an empty
evidence store.

Credentials are **never** stored here — they come from environment variables
(see [`../.env.example`](../.env.example)). Every numeric threshold lives in a
validated config field, not a literal at a call site (see
[`../AGENTS.md`](../AGENTS.md#non-negotiable-constraints)).

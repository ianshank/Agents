# Owner defaults — Deck B / agent-in-the-loop testgen

**Recorded:** 2026-09-06 · **Source:** board proceed · **Suggested OpenSpec option:** **(a)**
**Landed:** 2026-09-08 as **F-069 / ADR 0048**.

These are the locked evaluation-design defaults so eng can implement
`add-agent-in-the-loop-testgen` without re-litigating Deck B posture. They answer
`proposal.md` §"Evaluation-design questions" and close `tasks.md` §0.

> Implementation is a **registered** `testgen_agent` `TargetRunner` (not a second
> ADR 0039 hop). ADR 0039 applies only when `generator_path` names `module:attr`.
> Never allowlist `eval_harness`.

## Defaults (option a)

| Decision | Owner default |
|---|---|
| **Composition** | **(a) sequential pipeline `TargetRunner`** — generator → suite artifact → in-process `run_generated_suite`; single-`target` run shape; F-065 evidence contract reused |
| **Prompt policy** | **Held constant** across the held-out split (no per-item prompt tuning on sequestered items) |
| **Repetitions** | **`repetitions: 5`** on the generator so pass@k / pass^k finally measure generation variance. Do **not** quote those figures from a deterministic fake (`deterministic_sampling`). |
| **Held-out enforcement** | **Config allowlist + CI test** — `allowed_splits: [holdout]`; an offline CI test asserts train items fail closed. Quote **thorough holdout, n=11 unique**. |
| **Egress** | **Offline-only CI default**; live `model` target only in a **credential-gated** workflow (never the default Deck B CI job) |
| **Baseline beside the agent** | **Weak corpus slice + empty/null suite** (`config/testgen_agent_empty_eval.yaml`) — so the slide cannot imply absolute skill |
| **Deck B CI posture** | **Offline advisory `report_only`** — same day-one posture as F-065; no blocking thresholds until soak |
| **Scope** | **Testgen-only** registered pipeline; **advisory gates until soak**; do not generalise to engine multi-target graphs (option b) until a second scenario proves the pattern |

## Explicit non-choices (still deferred)

- Option **(b)** engine-level multi-step chaining — defer until a second scenario needs it.
- Option **(c)** external shell orchestration — rejected for Deck B (splits provenance out of `RunResult`).
- Publishing league tables / blocking gate thresholds before held-out soak distributions exist.
- RCA / requirements matrices (separate OpenSpec changes; archived as F-067 / F-068).

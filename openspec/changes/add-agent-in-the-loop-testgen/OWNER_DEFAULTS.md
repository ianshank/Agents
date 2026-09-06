# Owner defaults — Deck B / agent-in-the-loop testgen

**Recorded:** 2026-09-06 · **Source:** board proceed · **Suggested OpenSpec option:** **(a)**

These are the locked evaluation-design defaults so eng can implement
`add-agent-in-the-loop-testgen` without re-litigating Deck B posture. They answer
`proposal.md` §"Evaluation-design questions" and close `tasks.md` §0.

> **Doc-only.** No agent-in-the-loop coding starts from this record alone.

## Defaults (option a)

| Decision | Owner default |
|---|---|
| **Composition** | **(a) sequential pipeline `TargetRunner`** — generator → suite artifact → allowlisted `run_generated_suite`; single-`target` run shape; F-065 evidence contract reused |
| **Prompt policy** | **Held constant** across the held-out split (no per-item prompt tuning on sequestered items) |
| **Repetitions** | **`repetitions: 5`** on the generator so pass@k / pass^k finally measure generation variance |
| **Held-out enforcement** | **Manifest/config allowlist + CI test** — config or manifest key enforces the split; an offline CI test asserts the job cannot point the generator training loop at held-out items |
| **Egress** | **Offline-only CI default**; live `model` target only in a **credential-gated** workflow (never the default Deck B CI job) |
| **Baseline beside the agent** | **Weak corpus slice + empty/null suite** — so the slide cannot imply absolute skill |
| **Deck B CI posture** | **Offline advisory `report_only`** — same day-one posture as F-065; no blocking thresholds until soak |
| **Scope** | **Testgen-only** outer allowlisted runner; **advisory gates until soak**; do not generalise to engine multi-target graphs (option b) until a second scenario proves the pattern |

## Explicit non-choices (still deferred)

- Option **(b)** engine-level multi-step chaining — defer until a second scenario needs it.
- Option **(c)** external shell orchestration — rejected for Deck B (splits provenance out of `RunResult`).
- Publishing league tables / blocking gate thresholds before held-out soak distributions exist.
- RCA / requirements matrices (separate OpenSpec changes).

## Eng follow-ups (not started here)

1. Land design ADR at implementation time (claim number at land).
2. Implement pipeline `TargetRunner` per `tasks.md` §2 with ADR 0039 allowlisting preserved.
3. Date the Deck B estimate in `docs/plans/scenario-eval-matrices/DELIVERY.md` only after coding starts and a real date is known.

# backend-validation — eval-backend-validation_v1

Empirical, decision-grade evidence for the **D-0 displacement decision**: do the top
self-hostable eval backends (**Langfuse**, **Opik**) actually do what the capability matrix
(`Eval_Harness_Test_Matrix_v2.xlsx`, external to this repo) claims? Probes exercise running
deployments and record raw observables; a **human-signed rubric** maps observables to marks
(● / ◐ / —). Agents implement and execute; they never author acceptance criteria, never
break ties, and never recommend a platform — **the final report has no recommendation
section by design.**

Explicit non-goals: platform selection (human decision), the other 38 matrix rows,
decay-watch of volatile claims (deferred Phase D), UI/ergonomics judgments.

## Probe layers

| Layer | Question it answers | Mechanism |
|---|---|---|
| **L1 capability** | "Is the matrix right?" | Each tool's own SDK/API — harness-independent by construction (nothing outside `probes/l2_*` may import `eval_harness`; a unit test enforces it) |
| **L2 integration** | "What does adoption cost?" | Only the repo's vendor-neutral seam (`eval_harness.core.interfaces.ResultSink` + `RunResult`). The experiment-local `OpikSink` adapter IS the adapter-delta metric. No unified tracer/client Protocol exists in the harness — below-sink scope is reported **BLOCKED**, never improvised |
| **L3 air-gap** | "Is `Air-Gapped: Yes` true?" | Full L1 re-run on an `internal: true` network from an in-network prober container, dual-scored **as-shipped** vs **after documented telemetry opt-out**, with a DNS-witness recording every attempted external lookup |

## Phases and gates

| Phase | Command | Gate (fail-safe-to-escalate: BLOCKED report, never a silent skip) |
|---|---|---|
| P0 | `make preflight` | env checks + TCB validation → **exit 3 until the human sign-off exists** |
| P1 | `make deploy` | all three stacks healthy (langfuse, opik, judge) or BLOCKED naming the failure; ops-burden metrics recorded |
| P2 | `make l1` | negative controls must FAIL; an unexpected PASS **HALTs** (exit 4) for human review |
| P3 | `make l2` | precondition: harness sink seam importable; otherwise BLOCKED |
| P4 | `make airgap` | egress observation available or BLOCKED; dual scoring always |
| P5 | `make report` | renders `claimed_vs_observed.md`, `effort_metrics.json`, `airgap_report.md` |

Exit codes: `0` OK · `1` FAIL · `2` usage/config error · `3` BLOCKED · `4` HALT.

## Sign-off (the P0 gate)

`PROBES.yaml` and `RUBRIC.md` are TCB artifacts. Until a human corrects every `CLAIM_TBD`,
sets `signed_off: true` in both, and writes the `SIGNOFF` hash file (procedure at the bottom
of `RUBRIC.md`), **no probe executes**. Agents never write `SIGNOFF` — the same authorship
rule as the repo's `eval-change-approved` label.

## Zero-writes rule

Everything this experiment writes lands inside this subtree: settings refuse output
directories that escape it, compose files may only bind-mount paths under it, and the
PR-scoped `make isolation` check verifies the git diff touches nothing outside the
allowlist. The subtree consumes the repo core as a dependency only.

## Runbook (human)

1. Transcribe/correct claimed marks from the external matrix into `PROBES.yaml`; review the
   rubric; sign both (see `RUBRIC.md`).
2. `cp .env.example .env.local`, fill credentials (Langfuse keys come from the stack's
   headless init on first deploy).
3. `make deploy` → `make l1` → `make l2` → `make airgap` → `make report`
   (or `make all-phases`). Every run appends evidence to `artifacts/<run-id>/` (gitignored).
4. Commit the curated outputs from `reports/` via a reviewed PR.

Reproducibility (spec R11): compose images are digest-pinned (`deploy/DIGESTS.md`); the
judge model tag and every tool version land in the report. `make pin-digests` refreshes
pins deliberately — `deploy` refuses unpinned images.

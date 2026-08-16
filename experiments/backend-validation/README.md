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
   (or `make all-phases`; P4 rides the chain only via `cli all --with-airgap`). Every run
   appends evidence to `artifacts/<run-id>/` (gitignored). `make status` shows all five
   compose projects.
4. Commit the curated outputs from `reports/` via a reviewed PR.

## Air-gap mechanics (P4)

`make airgap` re-runs L1 from an in-network prober container per backend, dual-scored
as-shipped vs opt-out. Details that matter when reading its evidence:

- **Witness + canary.** A CoreDNS sidecar logs every DNS query and resolves nothing
  (NXDOMAIN). Docker's embedded DNS answers *service names* locally and forwards only
  external lookups, so a clean opt-out run would log nothing — a deliberate canary lookup
  (`bv-witness-canary.invalid`, excluded from egress classification) proves the witness
  was alive. An iptables byte-counter backstop is used ONLY when the run's own bridge
  DROP rule is positively identified; anything ambiguous degrades to witness-only and is
  recorded as degraded, never as a trustworthy zero.
- **Judge and network topology.** `make deploy` ensure-creates the shared `bv-judge-net`
  network (server-side evaluators dial `http://bv-judge:11434` over it — the judge's host
  port binds to 127.0.0.1 and is unreachable from containers). The air-gap overlays
  `!override` that attachment away, so the sealed stacks cannot reach the judge:
  judge-class probes error inside the seal BY DESIGN — the verdict keys off egress
  observation, not probe pass/fail.
- **Prober.** Built once per run (`docker build`, needs registry access — build while
  online; the sealed runs only `docker run` it). It writes observables through the one
  sanctioned bind mount (`artifacts/`); files land root-owned on the host.
- **Failure semantics.** Prober exit 4 propagates HALT (a negative control passed inside
  the seal — human review before ANY further runs); any other prober failure makes that
  observation unusable → BLOCKED. A dead witness can never confirm an air gap.

Reproducibility (spec R11): compose images are digest-pinned (`deploy/DIGESTS.md`); the
judge model tag and every tool version land in the report. `make pin-digests` refreshes
pins deliberately — `deploy` refuses unpinned images.

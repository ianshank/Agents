# VP deck — default eval operations UI

**Companion to:** [`../../executive-report-eval-tools.md`](../../executive-report-eval-tools.md), [`PLAN.md`](./PLAN.md), [`DELIVERY.md`](./DELIVERY.md), [`DECK_A_PLUS.md`](./DECK_A_PLUS.md)
**Date:** 2026-09-13 · **Census:** 67 `done` + 2 `deferred` (F-008, F-036) of 69 in `features.yaml`
**Purpose:** Speaker-ready copy (paste into Slides/PowerPoint). This *is* the deck PLAN.md declined to write.
**Evidence basis:** Vendor scores are expert judgment, not a bake-off. Discrimination table re-measured this date at `run.repetitions=1`.

### Timing

- **Full (12 slides, ~20 min)** including measurement trust.
- **Tool-choice cut (~12 min):** speak **1, 5–9, 12** only; hold 2–4 and 10–11 for questions.

---

## Slide 1 — Decision in one line

**Title:** Default eval UI this quarter: Phoenix. Not the scorer.

**Say:**

- We are choosing a **default operations UI / telemetry sink** — where humans look at traces and experiments.
- Testgen, RCA, and requirements **scores are computed by this harness** (F-065 / F-067 / F-068 / F-069). Vendors do not run those scorers.
- **Recommendation: Option 1** — Arize Phoenix as default tracing / RCA UI. Langfuse and BrainTrust seams stay. **No rename** of `langfuse-eval-harness` this quarter.

**Do not say:** “we measured vendors at test generation” or “Phoenix generates better tests.”

---

## Slide 2 — Two questions (do not mix)

**Title:** Two different decisions

1. **(A) Can we trust *our* numbers?** Measurement system. Deck A+.
2. **(B) Which UI do we operate?** Langfuse / Phoenix / BrainTrust as sinks.

Mixing them is how the September 7 report almost failed in a hostile room: vendor 0–10s looked like bake-off results for workloads the harness already scores.

---

## Slide 3 — Instrument check (n=60)

**Title:** The instrument separates known-good from known-bad

We built a corpus with known-good and known-bad suites so scorers could be checked against a known answer. Re-run 2026-09-13, `run.repetitions=1`, allowlist `eval_harness.targets.testgen`.

| Slice | Executability | Mutation | False-alarm | Obligation recall |
|---|---|---|---|---|
| `thorough` — known-good | 1.000 | 1.000 | 0.000 | 1.000 |
| `weak` — known-bad (detection) | 1.000 | **0.322** | 0.000 | **0.260** |
| `false_alarm` — known-bad (precision) | 1.000 | 1.000 | **0.397** | 1.000 |
| `broken` — non-executable | **0.000** | pass_rate n/a | pass_rate n/a | pass_rate n/a |

**n=60 per slice, 240 across four slices. Never n=300.** (`repetitions: 5` on a deterministic callable is a 5× multiplier with no new information.)

**Say in this order:** we built the weak slice to discriminate, then verified that it does.

Thorough 1.000 is the **corpus grading its own reference suite**. No agent wrote those tests.

On `broken`, dependents print a mean but `pass_rate=n/a` — absent evidence is not a passing rate. Advisory breaches print `~ (advisory, non-blocking)` and the run still ends `QUALITY GATE: PASS`.

---

## Slide 4 — What we will not claim

- **No live agent performance.** F-069 pipeline is shipped; committed `config/testgen_agent_eval.yaml` has **no** `generator_path`. Do not quote `pass^k` / n=55 from that deterministic fake. If a number appears, quote thorough **holdout n=11 unique** only after a live generator exists (ADR 0039 allowlist; never allowlist `eval_harness`).
- **No κ / ECE / Brier / AUROC as live results.** Zero `HUMAN_AUDIT` labels; calibration is an empty query until labeling is funded.
- **67 executable proofs run on every PR.** Two more are declared and deferred — **F-008 and F-036** — their proofs do not run, and the ledger says so. Never “63/63” or “67/67” as a coverage ratio: `validate.py` runs exactly the `done` set.

---

## Slide 5 — Use-case *operations* winners

**Title:** Who wins the UI, not the scorer

| Workload | Harness owns | Operations-UX winner (expert judgment) |
|---|---|---|
| Testgen | mutation / executability / green-on-correct / recall | BrainTrust `autoevals` + experiment rows |
| RCA | `rca_*` on synthetic corpus (F-067) | Phoenix OpenInference waterfalls |
| Requirements | `req_*` + provenance (F-068) | BrainTrust factuality heuristics |

Phoenix 9.5 on RCA is trace UX. BrainTrust 9.0 on testgen is experiment UX. Neither number is `testgen_mutation_score` or `rca_ac_at_k`.

---

## Slide 6 — Chart

**Title:** Seven dimensions, expert judgment

![Evaluation tools comparison](../../eval_metrics_comparison.png)

**Caption:** Expert judgment from spike reports — not a live bake-off. Unweighted mean: Phoenix **8.8**, Langfuse **8.0**, BrainTrust **7.6**. Source: [`docs/eval_metrics.json`](../../eval_metrics.json) v1.1.0.

A later bake-off can reorder 8.8 vs 8.0 without touching the air-gap or OTel arguments.

---

## Slide 7 — Air-gap, OTel, TCO shape

| | Phoenix | Langfuse | BrainTrust |
|---|---|---|---|
| Deploy | One container `arizephoenix/phoenix:17.18.0` (or SQLite) | Compose: Postgres + ClickHouse + web | Cloud SaaS / enterprise VPC |
| Wire | OTLP / OpenInference | Native SDK (+ OTLP bridge) | `experiment.log` / OTLP ingest |
| Air-gap score (expert) | 9.5 | 8.0 | 5.0 |
| Money | No vendor license; our VM | OSS self-host or trace-volume cloud | Seats + per-eval |

**Do not invent dollars.** Unscored: SSO, RBAC, residency, support SKUs.

---

## Slide 8 — CHARTER and the package name

- This repo is an **evaluation harness**, not a general observability platform ([CHARTER](../../CHARTER.md) §3).
- Choosing Phoenix as default **sink/UI** is not a CHARTER amendment and not a rename.
- `langfuse-eval-harness` and [ADR 0003](../../decisions/0003-langfuse-integration.md) stay. Phoenix was spiked to run *alongside* Langfuse.

---

## Slide 9 — Four options

1. **Phoenix default (recommended)** — tracing / RCA UI; other seams remain.
2. **Phoenix + `autoevals`** — Option 1 plus standalone offline heuristics (already registered). No BrainTrust SaaS.
3. **Langfuse default** — prompt-ops UI for non-engineers; name-aligned.
4. **Defer** — keep all three optional, default off. Today’s code. A real decision, not indecision.

---

## Slide 10 — Explicitly not deciding

Leave these in [`../vp-strategic-deep-dive/DECISIONS.md`](../vp-strategic-deep-dive/DECISIONS.md):

- Opik D-0 (`experiments/backend-validation`): unsigned TCB, Langfuse vs Opik only, agents cannot write `SIGNOFF`.
- Branch protection on `main` (ADR 0037).
- HUMAN_AUDIT funding / golden corpus (two annotators, κ ≥ 0.60, floor 50).
- B1: real incident telemetry vs synthetic-only RCA.

---

## Slide 11 — Residual risk

- Scores are **not** a live three-vendor bake-off.
- Optional next empirical step **after** Option 1–4 is recorded: human signs backend-validation, or a later Phoenix/BrainTrust probe.
- That step is **not** a blocker for today’s ask.

---

## Slide 12 — The ask

**Pick 1, 2, 3, or 4 before leaving. Record owner and date.**

Recommended: **Option 1**, with Option 2 if heuristic scoring UX matters this quarter.

---

## Hostile Q&A

1. **How was Phoenix 9.5 on RCA measured?** It was not. Expert judgment of tracing UX. F-067 scorers are harness-side.
2. **Does Phoenix generate better tests?** No. F-065 / F-069 scorers do not call Phoenix.
3. **Why isn’t Opik on the slide?** Separate unsigned experiment, Langfuse vs Opik, P0 blocked on human `SIGNOFF`.
4. **Are we dropping Langfuse / renaming?** No this quarter. Option 1 is default UI, not exclusive.
5. **Can we keep all three?** Yes — Option 4 and today’s code.
6. **Air-gap not required — still Phoenix?** Then the tree splits on trace debugging vs prompt-ops vs experiment diffs. Option 3 / 2 become live.
7. **Why 69 vs 67?** Two deferred features, named (F-008, F-036). The validator runs only the `done` set.
8. **n=300?** Five identical repetitions of 60 deterministic items. Quote **n=60**.
9. **When do we see agent numbers?** After a live `generator_path` (ADR 0039; never allowlist `eval_harness`). Holdout n=11 unique. Do not quote the empty/fail-closed config.
10. **Who pays for labels?** Not this meeting. DECISIONS.md §4: two annotators, κ ≥ 0.60, floor 50.

---

## Numbers that must not appear

Copied from [`DELIVERY.md`](./DELIVERY.md) §6 so they cannot creep back from older notes.

| Do not say | Why | Say instead |
|---|---|---|
| “our test generation scores 1.0 on mutation / executability / recall” as an agent result | Corpus’s own reference suite; `inputs.suite` pre-supplied | “the instrument separates known-good from known-bad: 1.000 vs 0.322 mutation, 0.000 vs 0.397 false-alarm, n=60 per slice” |
| “we measured our agents at test generation” | No committed generator; nothing chains a live model into `testgen_agent` in the shipped YAML | “scorers, corpus, and sandbox are done; live generator is next” |
| “n=300” for any testgen figure | 5× multiplier on 60 deterministic items | **n=60** |
| “63/63” or “67/67” as coverage | Tool runs exactly the `done` set | “67 runnable proofs; 2 deferred and named” |
| “zero scenario scorers implemented” | F-065 / F-067 / F-068 shipped | “scenario scorers shipped; no live agent measured through them yet” |
| “the audit found 24 issues” | Audit 20; review +4 | “20 from the audit, 4 from an automated review afterwards” |
| “OpenRCA agents went 10% → 33%” | Vendor self-report vs independent 12.5% | Independent full-benchmark figures only |
| any κ / ECE / Brier / AUROC as live results | Nothing to compute without labels | “instrumented; labels are the dependency” |
| Phoenix / Langfuse / BrainTrust 0–10s as “measured” | Expert judgment in `eval_metrics.json` | “expert judgment, spike-grounded” |

---

## Day-of rehearsal (human)

- [ ] `demo/run_demo.sh` on the presenting machine, clean clone, **day of**
- [ ] Pre-open `out/demo/report-fail.html`; know `helpfulness.mean=0.844` vs min 0.95, exit 1
- [ ] Discrimination table at n=60; no n=300 in any pasted slide
- [ ] Rehearse “this is not an agent result” and “this is not a vendor bake-off” until automatic
- [ ] Rehearse “why 69 and 67?” — F-008 and F-036, named
- [ ] If they refuse markdown in the room, paste this file into the org slide tool

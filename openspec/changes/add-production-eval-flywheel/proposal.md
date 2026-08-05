# Change: add-production-eval-flywheel

**Status:** blocked · **Date:** 2026-08-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/agent-eval-coverage/REVIEW.md`
**Blocked on:** a CHARTER §3 Ratified Amendment plus its own ADR. See "Why this is blocked" below.
**Depends on:** changes 1–3 (a candidate record carries trajectory and state evidence)
**Compiles down to:** `docs/plans/agent-eval-coverage/PLAN.md` + F-IDs (claimed at land) + an ADR.

## Why

Confirmed failures in production should become permanent offline regression cases. Today they do
not: there is no path from a sampled production trace to a versioned evaluation corpus.

The gap is narrower than the source analysis claimed. A human review queue already exists (F-034),
passive labelling from CI signals exists (F-033), and durable cross-run persistence exists (F-032,
ADR 0018). What is missing is **agent task traces** feeding that machinery, and a failure taxonomy
to classify them. This change supplies the missing input path; it does not rebuild the queue
(`REVIEW.md` §A5).

It also supersedes deferred **F-036** ("Real-transcript corpus bridge — flow_corpus ingestion from
labeled store records"), which addressed part of the same problem and was deliberately parked.

## Why this is blocked

CHARTER §3 states: *"This remains an evaluation harness, not a model trainer, an autonomous merge
bot, or a general observability platform."* A production trace-ingestion, redaction, deduplication
and review-queue pipeline is a scope expansion, not merely a new capability. Under CHARTER §6 it
needs a Ratified Amendment and its own ADR **before** this proposal is accepted — the same route the
calibrated auto-merge gate took through ADR 0005 (`REVIEW.md` §B13).

ADR 0031 authorises additive core-model and engine changes for agent evaluation. It does **not**
authorise this. Do not begin implementation on the strength of it.

## What changes (once unblocked)

- A versioned trace-envelope schema: trace ID, source type, model and agent version, input, output,
  trajectory, state evidence, user feedback, human-takeover reason, cost, latency, redaction status.
- Deterministic redaction validation, gating entry into the corpus.
- A failure taxonomy: wrong tool, invalid arguments, missing state mutation, policy violation, loop,
  no recovery, hallucinated success, judge disagreement, latency, cost, human escalation.
- Deduplication by normalised task and failure fingerprint.
- Promotion of human-approved candidates into a versioned golden dataset with provenance.
- A CI job consuming **committed fixtures only**.

## Scope / non-goals

- **Non-goal: request-time guardrails.** Evaluation is offline or asynchronous; guardrails enforce at
  request time. Permanently out of scope.
- **Non-goal: live evaluation in merge CI.** CHARTER §3 and F-006: the regression gate is diff-only
  and never runs live-judge or Langfuse evaluations. The ingestion CI job reads committed fixtures.
- **Non-goal: rebuilding the human review queue.** F-034 exists and is reused.
- **Non-goal: unredacted production data in the repository.** Redaction is a precondition of entry,
  validated deterministically, and CHARTER §4 invariant 7 forbids secrets in the tree outright.

## Impact

- Operational data flow, `.github/**` workflows, and privacy boundaries — the highest-risk of the
  five changes, which is why it is last and separately gated.
- **Protected paths:** `.github/**`, `config/**`, `tests/**`, `features.yaml`,
  `scripts/validations/**`.

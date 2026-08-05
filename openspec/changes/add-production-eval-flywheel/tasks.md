# Tasks: add-production-eval-flywheel

**Blocked.** Do not start until the CHARTER §3 amendment and this change's ADR are accepted.

`[P]` = protected path. Coverage floor stated per package at implementation time.

## 0. Unblock — human decision required
- [ ] CHARTER §3 Ratified Amendment for production trace ingestion.
- [ ] A numbered ADR recording the scope expansion, trust boundary and privacy posture.
- [ ] Confirm this supersedes deferred F-036 and update that entry accordingly.

## 1. Schema
- [ ] Versioned trace-envelope schema: trace ID, source type, model and agent version, input,
      output, trajectory, state evidence, user feedback, human-takeover reason, cost, latency,
      redaction status.
- [ ] Forward-compatible unknown-field handling, following ADR 0025's fail-closed posture.

## 2. Redaction
- [ ] Deterministic redaction validation, failing closed.
- [ ] Assert an unredacted record writes nothing at all — not a partial record.

## 3. Classification and dedup
- [ ] Failure taxonomy: wrong tool, invalid arguments, missing state mutation, policy violation,
      loop, no recovery, hallucinated success, judge disagreement, latency, cost, human escalation.
- [ ] Deduplication by normalised task + failure fingerprint, carrying an occurrence count.

## 4. Review and promotion
- [ ] Reuse F-034's queue and approval record; do not build a second one.
- [ ] Export approved records to the existing corpus format.
- [ ] Regression-suite manifest with provenance.
- [ ] Track golden-set growth and report stale, unexercised cases.

## 5. CI
- [ ] `[P]` A CI job consuming committed fixtures only.
- [ ] `[P]` Assert no production network access in merge CI.
- [ ] `[P]` Assert the pipeline makes no request-time allow/deny decision.

## 6. Governance
- [ ] `[P]` Claim the next free F-ID; add an executable proof.
- [ ] `[P]` Regenerate both `tests/*_baseline.json` if any public surface changes.
- [ ] CHANGELOG + documentation, including the guardrails-versus-evals distinction.

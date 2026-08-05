# Design: add-production-eval-flywheel

**This design is provisional.** The change is blocked on a CHARTER §3 Ratified Amendment and its own
ADR (see `proposal.md`). Nothing here should be implemented before that decision.

## Pipeline

```
Production trace
      │
      ▼  Redaction + schema validation   ← fails closed; unredacted records never land
      ▼  Failure classification          ← fixed taxonomy, not free text
      ▼  Deduplication                   ← normalised task + failure fingerprint
      ▼  Candidate regression record
      ▼  Human review / expected outcome ← reuses F-034's queue, does not rebuild it
      ▼  Versioned golden dataset
      ▼  Offline CI evaluation           ← committed fixtures only
      ▼  Regression report
```

## What is reused rather than rebuilt

| Need | Existing mechanism |
|---|---|
| Human review queue and verdict dispatch | F-034 (`merge-gate-audit.yml`, `merge-gate-verdict.yml`, `record_audit_verdict.py`) |
| Durable store across ephemeral runners | F-032 / ADR 0018 (`agent_core.store_sync`, orphan data branch) |
| Passive labelling from CI signals | F-033 (`agent_core.outcome_labeller`) |
| Corpus assembly and validation | `dataset-lint`, `eval-corpus-forge` skills |

The source analysis proposed building a review queue from scratch. One exists; duplicating it would
also duplicate its trust boundary, which is the part that took the most care to get right (F-034's
verdict workflow is the *only* automated writer of the authoritative label, and is human-triggered
by construction).

## Trust boundary

Ingestion is a **reader** of production and a **writer** of candidates. It never writes an
authoritative label and never makes a request-time decision. The human approval step is the only
path from candidate to gating corpus, mirroring the merge gate's posture where `HUMAN_AUDIT` is the
sole authoritative label source.

## Privacy

Redaction validation is deterministic and fails closed. CHARTER §4 invariant 7 already forbids
secrets and host-specific data in the tree, and F-048's gitleaks gate enforces it — but a gate that
catches a leak after it lands is a worse position than never ingesting it, so redaction gates entry
rather than relying on the scan.

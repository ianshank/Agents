# Review: add-production-eval-flywheel

**Reviewed:** the externally proposed production-flywheel change against `b52c696`. Full findings:
`docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

Correctly placed last, and correctly constrained: offline, redacted, human-approved, and out of
merge CI. Those four constraints are the right ones and are kept verbatim. The change is
nonetheless **blocked**, because it is a scope expansion that neither source document routed through
the charter.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| B13 | Treated as an ordinary change | CHARTER §3 excludes "a general observability platform". Requires a Ratified Amendment plus its own ADR before acceptance, as ADR 0005 did for auto-merge. Status set to `blocked` |
| A5 | Assumed no human review queue exists | F-034 ships one, with the trust boundary already worked out. Reused, not rebuilt |
| A6 | Presented as an unnoticed gap | Partly overlaps deferred F-036, which this supersedes explicitly |
| — | Redaction placed after ingestion | Made a precondition of entry. A leak caught by gitleaks after it lands is a worse position than never ingesting it |

## Assumptions challenged

**Could production ingestion leak secrets or personal data?** This is the change's central risk, and
the answer must be structural rather than procedural. Redaction gates entry and fails closed; an
unredacted record writes nothing at all, not a partial record. CHARTER §4 invariant 7 and F-048's
gitleaks gate are the backstop, not the primary control.

**Does CI remain deterministic and offline?** Yes, and it is a requirement with its own scenario.
The ingestion job consumes committed fixtures. This preserves F-006's diff-only regression gate and
CHARTER §3's "gates never run live evaluations".

**Can this pipeline make a request-time decision?** No, and the spec says so as a negative
requirement rather than leaving it implied. An ingestion path that grows an allow/deny opinion has
become a guardrail, which is a different system with a different failure mode.

**Does one recurring failure flood the corpus?** Not with fingerprint deduplication and an occurrence
count. Without it, the single most common production failure would dominate the golden set and
quietly reweight every aggregate computed over it.

**Are approved cases ever removed?** No — that is the point of "incidents become permanent
regression cases". But staleness reporting exists so that a corpus which has drifted out of use is
visible rather than assumed live. A frozen eval suite nobody exercises is one of the anti-patterns
the source analysis correctly named.

## Residual risk

- **This is the change most likely to be attempted early**, because it is the most visible. Its
  dependencies (trajectory, reliability, state) are real: without them a candidate record carries
  only input and output text, which is precisely the shallow evaluation the whole effort exists to
  move past.
- **Human approval is the throughput bottleneck by design.** The same `audit_capacity_per_cycle`
  constraint that governs merge-gate calibration applies here, and no amount of automated
  classification relieves it.

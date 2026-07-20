# RUBRIC.md — observable → mark mapping (TCB artifact)

This rubric is the ONLY thing that turns raw probe observables into grid marks
(● full / ◐ partial / — absent). Probes record what happened; this document decides what
it means. It is human-authored and human-signed: agents implement and execute it, they do
not amend it (spec R3). Anything the rubric cannot resolve is reported as `HUMAN`, never
tie-broken by an agent (spec scoring rule 4).

## How marks are computed

1. Every probe run produces observables `{operation, status, latency_ms, artifact_ids,
   stderr, ...}` plus probe-specific boolean evidence fields. A cell's `expected_observables`
   in `PROBES.yaml` are predicates over those records.
2. For `deterministic` cells (k=1) a predicate holds iff it holds in the single run. For
   `judge_k3` cells a predicate holds iff it holds in the **majority** of the 3 runs; any
   disagreement across runs flags the cell `flaky` and the per-run outcomes are reported
   side by side — disagreement is evidence, never averaged away (spec R6, scoring rule 3).
3. The machine block below maps "which predicates held" to a mark. Expected-fail probes
   (negative controls, spec R5) are NOT marked: a control that fails as expected is
   `confirmed-absent`; a control that passes unexpectedly HALTS the whole run for human
   review — either the matrix is wrong (a finding) or the probe layer is broken.
4. `human-only` / `doc-only` cells are never marked by agents; the report carries
   `observed: not-probed (<classification>)` for them (spec R2).

## Machine-readable rules

The fenced block below is the exact input `backend_validation.rubric` executes. It is part
of the signed artifact: editing it invalidates the SIGNOFF hashes.

<!-- rubric:machine -->
```yaml
rubric_version: 1
mapping:
  default:
    full: {all_expected_hold: true}
    partial: {some_expected_hold: true}
    absent: {otherwise: true}
  overrides:
    # RAG metrics: the matrix's own ◐ boundary — at least half of the expected
    # observables holding is still "partial", below half is "absent".
    - cell: rag.metrics
      partial: {min_expected_fraction: 0.5}
flags:
  flaky: "k=3 repetitions disagree on any predicate; reported per-rep, never averaged"
  blocked: "a precondition failed; the row carries BLOCKED and no mark"
halt:
  unexpected_control_pass: true
signoff:
  signed_off: false
  signed_by: null
  signed_date: null
```

## Sign-off procedure (human)

1. Correct every `CLAIM_TBD` in `PROBES.yaml` against the external matrix; review every
   predicate and this rubric.
2. Set `signed_off: true` (plus `signed_by`, `signed_date`) in BOTH `PROBES.yaml` and the
   machine block above.
3. Write the `SIGNOFF` file next to this document:

   ```
   sha256 <hex of PROBES.yaml>  PROBES.yaml
   sha256 <hex of RUBRIC.md>  RUBRIC.md
   signed_by: <name>
   ```

   (`sha256sum PROBES.yaml RUBRIC.md` produces the hashes; hash RUBRIC.md AFTER setting its
   `signed_off` flag.)
4. `preflight` recomputes both hashes and refuses to run probes on any mismatch — a signed
   file that later drifts is mechanically detected. Agents NEVER write `SIGNOFF` (the same
   authorship rule as the repo's `eval-change-approved` label).

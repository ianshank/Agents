# Runbook: weekly merge-gate audit triage

HUMAN_AUDIT labels are the only rows that feed `tau` / calibrator health.
TIMEOUT_CLEAN is an optimistic weak positive and **does not** underwrite
auto-merge. This runbook is the human cadence that turns shadow-mode
infrastructure into activation-bar progress.

## Cadence

The `merge-gate-audit.yml` workflow already selects an unbiased sample weekly
(Monday cron) and opens `merge-gate-audit` issues. Triage is: **close the issues
with a verdict**, do not re-sample by hand.

1. Open issues labeled `merge-gate-audit`.
2. For each issue, inspect the change (diff, CI, revert/failure signals).
3. Record the verdict via `merge-gate-verdict.yml` `workflow_dispatch`
   (`change_id` = merge commit SHA, `verdict` = correct | incorrect,
   `selection_propensity` copied from the issue).
4. Do not let an agent click the dispatch. Authorization is the
   `merge-gate-verdict` environment plus optional `MERGE_GATE_AUDITORS`.

## Progress against the activation bar

```bash
python -m agent_core.store_sync stats --store merge_outcomes.jsonl --soak-progress
```

`--soak-progress` uses `SoakConfig.target_per_domain` (default 380, ADR 0005
sample-size note). `--soak-target N` wins when both are passed. The `_soak`
block reports `remaining_by_domain` in HUMAN_AUDIT counts, not total rows.

The audit workflow now prints the same block after selection so the weekly
run's summary is the remaining-to-bar figure, not just issue count.

## Labeling rules (short)

Full protocol: [labeling-protocol.md](labeling-protocol.md).

- Two annotators for golden-corpus / judge work; merge-gate audit issues are
  single-auditor by construction (the dispatch is one verdict) — disagreements
  on the golden set escalate, they are not averaged.
- Never record TIMEOUT_CLEAN as if it were HUMAN_AUDIT.
- `record_verdict` in the library is non-idempotent (appends a second row and
  logs a warning). Use `scripts/record_audit_verdict.py` for the SHA-validated
  no-op wrapper.

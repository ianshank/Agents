---
name: merge-gate-auditor
description: Sample unlabelled PR records from merge-gate-data, prepare structured Audit Verdict Cards, and stage human verdicts. Use whenever sampling unlabelled audit candidates, conducting merge-gate audit triage, or reviewing pull-request outcomes against the calibrated merge gate.
---

# Merge Gate Auditor — Human Audit Triage Skill

The `merge-gate-auditor` automates the sampling of unlabelled pull request records from `origin/merge-gate-data`, formats detailed diff and behavioral contexts, and constructs Audit Verdict Cards for review by the human merge owner (`@ianshank`).

## Core Invariants

1. **Zero Synthetic Audits**: Never synthesize or fabricate `HUMAN_AUDIT` records. The calibrated auto-merge gate requires genuine human audit evidence ($N \ge 200, ECE \le 0.05, AUROC \ge 0.65$).
2. **Cold-Start Floor**: The audit sampler enforces `AuditConfig.per_domain_floor` (default 30, workflow override 3) before a domain can exit cold-start.
3. **Plumbing Store Sync**: All reads and writes to `merge-gate-data` operate through `agent_core.store_sync` plumbing (`mktree`, `commit-tree`), never touching working trees or triggering CI (`[skip ci]`).

## Procedure

### 1. Pull Latest Store Records
```bash
python -m agent_core.store_sync pull --repo-dir . --store data/merge_outcomes.jsonl
```

### 2. Inspect Soak Progress
```bash
python -m agent_core.store_sync stats --store data/merge_outcomes.jsonl --soak-progress --audit-floor 3
```
Verify:
- Total records in store ($N$)
- Number of human audits accumulated per domain
- Cold-start status per domain
- Shortfall vs soak target

### 3. Sample Unlabelled Candidates
```bash
python -m agent_core.audit_sampler select --store data/merge_outcomes.jsonl --domain human/agent-core --count 5 --floor 3
```

### 4. Generate Audit Verdict Card
For each sampled candidate change ID:
1. Inspect git log and diff of the change:
   ```bash
   git show <change_id>
   ```
2. Verify if any post-merge revert or fix-up was committed within the 7-day observation window.
3. Check behavioral regression test status:
   ```bash
   python -m pytest behavioral-regression/tests/
   ```
4. Render the Audit Verdict Card:
   ```markdown
   ### Audit Verdict Card: `<change_id>`
   - **Domain**: `<domain>`
   - **Merged At**: `<timestamp>`
   - **Merge Gate Confidence**: `<raw_confidence>`
   - **Revert / Fixup Observed**: None / Commit `<sha>`
   - **Maintainer Actions**:
     - Confirm Correct: `python scripts/record_audit_verdict.py --store data/merge_outcomes.jsonl --change <change_id> --actor @ianshank --correct`
     - Confirm Regressed: `python scripts/record_audit_verdict.py --store data/merge_outcomes.jsonl --change <change_id> --actor @ianshank --incorrect`
   ```

### 5. Sync Human Verdicts to Remote Store
After human maintainer executes verdicts:
```bash
python -m agent_core.store_sync push --repo-dir . --store data/merge_outcomes.jsonl --actor @ianshank
```

## Definition of Done

- Unlabelled candidates are sampled strictly according to the domain cold-start floor.
- Verdict cards provide complete commit, diff, and revert context.
- No synthetic records are generated.
- Updated store records pass `agent_core.store_sync stats` validation.

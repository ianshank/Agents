# Epic 2: Calibrated Merge Gate & Predictive Calibration

## Focus Area
Statistical merge gate, isotonic calibration, domain routing, audit queues, and automated risk enforcement.

## Landed Features & Milestones
- **[x] Calibrated Merge Gate Core (F-010, ADR 0005)**: Predictive gating subsystem with Wilson intervals, cold-start `ESCALATE` posture, and opt-in execution.
- **[x] Real-Data Activation (F-032–F-035, ADR 0018)**: Outcome store on `merge-gate-data` branch, daily outcome labeller, weekly audit sampling queue, and seed-on-merge recording.
- **[x] Agent-Record Calibration Routing (F-042–F-044, F-046, F-061, ADR 0023)**: Deterministic proxy confidence calculation (`scripts/agent_confidence.py`), `agent_version` attribution, and calibration reporting.
- **[x] Calibrator Health & Wilson Floor Integrity (F-049, ADR 0029)**: `_operating_bin_ci_width` region evaluation, single-sourced binning, complexity optimization, and `GatePolicyConfig` parameter validation.
- **[x] Soak Observability (F-040)**: `soak_progress` monitoring and reporting tools.

## In Progress & Planned
1. **Accumulate Human Audit Labels**:
   - Execute weekly audit triage via `merge-gate-audit.yml` and record verdicts via `merge-gate-verdict.yml`.
   - Reach minimum sample floor across human and agent domains.
2. **Propensity-Weighted Calibration (F-047 follow-on)**:
   - Weight historical audit records by $1/p$ (selection propensity) to eliminate selection bias in calibration metrics.
3. **Calibrated Auto-Merge Activation**:
   - Review calibration health and Wilson bounds once required sample size is reached.
   - Flip `ENABLE_CALIBRATED_AUTOMERGE` variable per ADR 0005 checklist.

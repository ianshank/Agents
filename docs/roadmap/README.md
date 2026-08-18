# Engineering Roadmap & Epic Index

This directory breaks down the active and historical development epics for `ianshank/Agents` into domain-specific roadmap files.

## Active Epics & Index

| Epic | Domain | Key Features / ADRs | Status |
|---|---|---|---|
| **[Epic 1: Eval Matrix & Reliability](epic-1-eval-matrix-and-reliability.md)** | Evaluation Engine & Matrix | F-051 (Trajectory), F-053 (Matrix), ADR 0031, Repeat Reliability, Panel Judge | In Progress |
| **[Epic 2: Calibrated Merge Gate](epic-2-calibrated-merge-gate.md)** | Merge Gate & Calibration | F-010, F-032-F-035, F-040, F-047, F-049, ADR 0005, ADR 0029 | In Progress |
| **[Epic 3: Monorepo & CI Infrastructure](epic-3-monorepo-and-ci-infrastructure.md)** | Infrastructure, CI & Typing | F-006, F-007, F-031, F-039, ADR 0021, Nightly E2E, Python 3.11+ (ADR 0034) | In Progress |
| **[Epic 4: Skills & Marketplace](epic-4-skills-and-marketplace.md)** | Generator & Reasoning Skills | F-023, F-028, F-029, F-045, ADR 0020, ADR 0024, ADR 0030 | Active |
| **[Epic 5: Integrations & Plugins](epic-5-integrations-and-plugins.md)** | External Sinks & Ecosystem | F-038 (BrainTrust), Phoenix Live, ADR 0017 (Claude Foundation), Backend Validation | In Progress |

---

## High-Level Execution Tracker

- **Tier 1 (Ship & Stabilize)**: ✅ Version 1.3.0.dev0, Quickstart Guide, Scorer Protocol Migration, Cross-Platform E2E Windows Hardening, Nightly E2E CI (`.github/workflows/nightly-e2e.yml`).
- **Tier 2 (Operational Excellence)**: Roadmap split, Mypy strict coverage expansion, Human audit label accumulation, Branch protection enforcement.
- **Tier 3 (Architecture Evolution)**: Panel/Council Judge, Repeat Reliability Metrics (`pass^k`), Judge Bias Calibration, Claude Foundation repository extraction.

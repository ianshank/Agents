# Epic 4: Skills & Marketplace Ecosystem

## Focus Area
Agentic skill development, deterministic generators, reasoning plugins, and community marketplace validation.

## Landed Features & Milestones
- **[x] Skill Marketplace (F-023, ADR 0009)**: Centralized registry in `skills/marketplace.yaml` with schema enforcement and validation.
- **[x] Deterministic Generators (ADR 0020)**: `project-setup`, `quality-gate`, and `deploy` generator skills with deterministic output and byte-stability.
- **[x] Assertion Registries & dataset-lint (F-045, ADR 0024)**: `validate_skill.py` decoupled from assertion types using `ASSERTION_GRADERS` registry; standalone `dataset-lint` skill.
- **[x] Reasoning & Planning Skills**: Composable skills (`hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`).
- **[x] Skill CI Tiers (ADR 0030)**: Multi-tier CI gating (`code`, `generative`, `subjective`) with automated coverage validation.
- **[x] Two-pass `openspec-peer-review`**: mechanical fact-check against a pinned SHA plus adversarial design critique. Shipped with skill v1.1.0.
- **[x] `test-completeness-guard`**: census of frozen public-surface names against a test tree. Default floor is report-only; does not invent product coverage floors. Skills-CI coverage for the skill itself is 95%.

## In Progress & Planned
1. **`scaffold_change.py` Generator in `openspec-quality-plan`**:
   - Automate 5-file change proposal package scaffolding.

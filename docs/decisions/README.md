# Architecture Decision Records

Each ADR captures one decision: its **context**, the **decision**, and its
**consequences**. They are immutable once accepted — a later decision that
changes course is a *new* ADR that supersedes the old one, not an edit.

## Conventions

- Filename: `NNNN-kebab-case-title.md`, four-digit zero-padded number.
- Numbers are assigned in order and are **not contiguous by design** — `0007` is
  an intentional gap (see
  [`../plans/agents-critical-path/REVIEW.md`](../plans/agents-critical-path/REVIEW.md)).
  Do **not** backfill it or renumber later ADRs.
- Proposing a new ADR: copy the structure of a recent one, take the next free
  number, and open a PR. See [../../GOVERNANCE.md](../../GOVERNANCE.md).

## Index

| ADR | Title |
|---|---|
| [0001](0001-openai-compatible-judge.md) | Use OpenAI-compatible API for LLM judge integration |
| [0002](0002-skill-framework.md) | Reusable skill template and E2E skill validator |
| [0003](0003-langfuse-integration.md) | Langfuse tracing and hosted evaluation integration |
| [0004](0004-auto-fix-loop.md) | Agentic auto-fix loop (design-only, disabled) |
| [0005](0005-calibrated-merge-gate.md) | Calibrated auto-merge gate (opt-in, default-off) |
| [0006](0006-behavioral-regression-detection.md) | Behavioral-regression detection (calibrated, offline, fail-safe-to-escalate) |
| _0007_ | _intentionally unused (see conventions above)_ |
| [0008](0008-parallel-execution.md) | Parallel item execution (ThreadPoolExecutor, sequential fallback) |
| [0009](0009-tech-debt-audit-and-compat-surface.md) | Tech-debt audit, intentional compatibility surface, uniform 95% coverage |
| [0010](0010-langfuse-prompt-management.md) | Langfuse judge-prompt management (opt-in, YAML-fallback) |
| [0011](0011-multi-model-comparison.md) | Multi-model comparison (additive, opt-in) |
| [0012](0012-ab-eval-campaigns.md) | A/B eval campaigns with statistical significance (additive, opt-in) |
| [0013](0013-model-backed-target.md) | Real model-backed target (additive, opt-in) |
| [0014](0014-openai-judge-skill-modernization.md) | openai-judge skill modernization (uniform v2.0 convention) |
| [0015](0015-model-bench-marketplace-skill.md) | model-bench marketplace skill |
| [0016](0016-time-windowed-judge-rate-limit.md) | Time-windowed judge rate limiting (additive, opt-in) |
| [0017](0017-claude-foundation-reconciliation.md) | claude-foundation reconciliation |
| [0018](0018-outcome-store-persistence.md) | Merge-gate outcome-store persistence (dedicated data branch) |
| [0019](0019-size-budget-gate.md) | Structural size-budget enforcement (complexity, file/function length) |
| [0020](0020-deterministic-generator-skills.md) | Deterministic generator skills (project-setup / quality-gate / deploy) |
| [0021](0021-ci-gate-delegation.md) | CI gate delegation strategy |
| [0022](0022-determinism-boundary-for-inference-skills.md) | Determinism boundary for inference skills (consume, don't contain) |
| [0023](0023-agent-confidence-proxy-and-agent-domain-seeding.md) | Agent-confidence proxy + agent-domain seeding & backfill |
| [0024](0024-assertion-graders-registry.md) | Assertion graders registry and skill-validation alignment |

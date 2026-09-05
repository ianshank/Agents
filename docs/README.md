# Documentation

The documentation index for `ianshank/Agents`. This map mirrors the
"root documentation map" in [`AGENTS.md`](../AGENTS.md) so humans and coding
agents share one source of navigation. Prose docs also render as a site — see
[Building the docs site](#building-the-docs-site).

## Start here

| If you want to… | Read |
|---|---|
| Get running in 5 minutes | [quickstart.md](quickstart.md) |
| Install / run / test the harness | [../README.md](../README.md) |
| Know which doc answers what (and the guardrails) | [../AGENTS.md](../AGENTS.md) |
| Understand the north-star scope & invariants | [CHARTER.md](CHARTER.md) |
| Contribute | [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| Report a vulnerability | [../SECURITY.md](../SECURITY.md) |
| Get help | [../SUPPORT.md](../SUPPORT.md) |
| See a repeatable demo | [../demo/README.md](../demo/README.md) |

## Architecture

- [CHARTER.md](CHARTER.md) — Vision / Mission / Scope / Invariants / Roadmap.
- [c4_architecture.md](c4_architecture.md) — hand-maintained C4 context /
  container / sub-component diagrams (runtime/call semantics).
- [../architecture.mmd](../architecture.mmd) + [../architecture.yaml](../architecture.yaml)
  — the generated import-edge component view (drift-gated in CI).
- [matrix-coverage.md](matrix-coverage.md) — the generated eval-matrix coverage
  grid (components × dims, waivers, alias freezes, follow-on obligations;
  regenerate with `python tests/test_matrix_coverage.py --update` — freshness-gated
  in CI, never hand-edit).

## Decisions (ADRs)

Numbered Architecture Decision Records live in [decisions/](decisions/README.md).
See that index for the full list and the (intentional) numbering gap.

## Roadmap & Epics

Active engineering epics and architectural roadmap live in [roadmap/](roadmap/README.md):
- [Epic 1: Eval Matrix & Reliability](roadmap/epic-1-eval-matrix-and-reliability.md)
- [Epic 2: Calibrated Merge Gate](roadmap/epic-2-calibrated-merge-gate.md)
- [Epic 3: Monorepo & CI Infrastructure](roadmap/epic-3-monorepo-and-ci-infrastructure.md)
- [Epic 4: Skills & Marketplace](roadmap/epic-4-skills-and-marketplace.md)
- [Epic 5: Integrations & Plugins](roadmap/epic-5-integrations-and-plugins.md)


## Runbooks & operations

- [e2e-runbook.md](e2e-runbook.md) — running and reading the one-command
  end-to-end / user-journey harness.
- [e2e-matrix/](e2e-matrix/README.md) — the generated test matrix for a full end-to-end
  run (markdown, CSV and workbook renderings of one run report). See
  [e2e-matrix/ERRATA.md](e2e-matrix/ERRATA.md) for a known provenance defect in the
  committed artifact.

## Change proposals

- [`../openspec/`](../openspec/) — the reversible OpenSpec coordination layer: in-flight
  change proposals and the agent-ownership contract, compiled down to `features.yaml`
  F-IDs, `scripts/validations/F_*.py` proofs and ADRs. Mirrors the `openspec/` row in
  [`AGENTS.md`](../AGENTS.md)'s root documentation map.

## Spikes (reversible-adoption patterns)

- [phoenix-spike.md](phoenix-spike.md) — the SDK-optional Phoenix seam.
- [braintrust-spike.md](braintrust-spike.md) — the BrainTrust experiment-export seam.
- [openspec-spike.md](openspec-spike.md) — OpenSpec as a reversible coordination layer
  over the enforced `features.yaml` / `F_*.py` / ADR system (`openspec/`).

## Research

- [claude-code-ecosystem-research.md](claude-code-ecosystem-research.md) — survey of seven
  Claude Code ecosystem repos (repomix, the MCP reference servers, claude-mem, claude-hud,
  claude-context, rtk, awesome-claude-code) with per-repo adoption verdicts and a
  prioritized incorporation roadmap mapped to this repo's integration surfaces.

## Baselines & audits

- [gap-analysis-2026-07.md](gap-analysis-2026-07.md) — measured lint/type/coverage baseline.
- [gap-analysis-2026-07-remediation.md](gap-analysis-2026-07-remediation.md) — the remediation record.
- [gap-analysis-2026-07-py-typed-mypy.md](gap-analysis-2026-07-py-typed-mypy.md) — typing/`py.typed` follow-up.
- [gap-analysis-merge-gate-2026-07-24.md](gap-analysis-merge-gate-2026-07-24.md) — merge-gate /
  calibration subsystem: three fixed defects and ten open findings, each with its reproduction.

## Templates & conventions

- [STYLE.md](STYLE.md) — documentation style, taxonomy, naming conventions, and
  the shared component-README template.
- [SKILL_TEMPLATE.md](SKILL_TEMPLATE.md) / [SKILL_VALIDATION_TEMPLATE.md](SKILL_VALIDATION_TEMPLATE.md)
  — scaffolds for a new skill and its validation.

## Plans

Cross-cutting execution plans live under [plans/](plans/) as
`plans/<topic>/{PLAN.md,REVIEW.md}`. Every plan is listed here — an unlisted plan is
unreachable from any documented entry point, which is how eleven of them went invisible
before this index existed:

| Topic | Documents |
|---|---|
| agent-eval-coverage | [PLAN](plans/agent-eval-coverage/PLAN.md) · [REVIEW](plans/agent-eval-coverage/REVIEW.md) |
| agent-record-decontamination | [PLAN](plans/agent-record-decontamination/PLAN.md) · [REVIEW](plans/agent-record-decontamination/REVIEW.md) · [REVIEW-v2](plans/agent-record-decontamination/REVIEW-v2.md) |
| agents-critical-path | [PLAN](plans/agents-critical-path/PLAN.md) · [REVIEW](plans/agents-critical-path/REVIEW.md) |
| claude-foundation | [PLAN](plans/claude-foundation/PLAN.md) · [REVIEW](plans/claude-foundation/REVIEW.md) · [sources](plans/claude-foundation/sources.md) |
| enterprise-docs-overhaul | [PLAN](plans/enterprise-docs-overhaul/PLAN.md) · [GAP_ANALYSIS](plans/enterprise-docs-overhaul/GAP_ANALYSIS.md) |
| eval-delivery-sequencing | [PLAN](plans/eval-delivery-sequencing/PLAN.md) |
| eval-evidence-integrity | [PLAN](plans/eval-evidence-integrity/PLAN.md) · [REVIEW](plans/eval-evidence-integrity/REVIEW.md) |
| orbital-drift-alignment | [PLAN](plans/orbital-drift-alignment/PLAN.md) |
| real-data-activation | [PLAN](plans/real-data-activation/PLAN.md) · [REVIEW](plans/real-data-activation/REVIEW.md) |
| scenario-eval-matrices | [PLAN](plans/scenario-eval-matrices/PLAN.md) · [REVIEW](plans/scenario-eval-matrices/REVIEW.md) |

## Per-package docs

Each package carries its own README (and most a CHANGELOG / GAP_ANALYSIS):
[agent-core](../agent-core/README.md) ·
[behavioral-regression](../behavioral-regression/README.md) ·
[flow-corpus](../flow-corpus/README.md) ·
[flow-protocol](../flow-protocol/README.md) ·
[claude-foundation](../claude-foundation/README.md) ·
[eval_harness](../src/eval_harness/README.md) ·
[skills](../skills/README.md) · [scripts](../scripts/README.md) ·
[experiments](../experiments/README.md).

## Building the docs site

The prose docs render as a static site via `mkdocs-material`:

```bash
pip install -e '.[docs]'
mkdocs serve            # live preview at http://127.0.0.1:8000
mkdocs build            # render to ./site
```

Configuration is in [../mkdocs.yml](../mkdocs.yml).

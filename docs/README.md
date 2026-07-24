# Documentation

The documentation index for `ianshank/Agents`. This map mirrors the
"root documentation map" in [`AGENTS.md`](../AGENTS.md) so humans and coding
agents share one source of navigation. Prose docs also render as a site — see
[Building the docs site](#building-the-docs-site).

## Start here

| If you want to… | Read |
|---|---|
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

## Decisions (ADRs)

Numbered Architecture Decision Records live in [decisions/](decisions/README.md).
See that index for the full list and the (intentional) numbering gap.

## Runbooks & operations

- [e2e-runbook.md](e2e-runbook.md) — running and reading the one-command
  end-to-end / user-journey harness.

## Spikes (reversible-adoption patterns)

- [phoenix-spike.md](phoenix-spike.md) — the SDK-optional Phoenix seam.
- [braintrust-spike.md](braintrust-spike.md) — the BrainTrust experiment-export seam.

## Baselines & audits

- [gap-analysis-2026-07.md](gap-analysis-2026-07.md) — measured lint/type/coverage baseline.
- [gap-analysis-2026-07-remediation.md](gap-analysis-2026-07-remediation.md) — the remediation record.
- [gap-analysis-2026-07-py-typed-mypy.md](gap-analysis-2026-07-py-typed-mypy.md) — typing/`py.typed` follow-up.

## Templates & conventions

- [STYLE.md](STYLE.md) — documentation style, taxonomy, naming conventions, and
  the shared component-README template.
- [SKILL_TEMPLATE.md](SKILL_TEMPLATE.md) / [SKILL_VALIDATION_TEMPLATE.md](SKILL_VALIDATION_TEMPLATE.md)
  — scaffolds for a new skill and its validation.

## Plans

Cross-cutting execution plans live under [plans/](plans/) as
`plans/<topic>/{PLAN.md,REVIEW.md}` (e.g.
[plans/enterprise-docs-overhaul/PLAN.md](plans/enterprise-docs-overhaul/PLAN.md)).

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

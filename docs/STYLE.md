# Documentation Style & Taxonomy

How documentation is organized in this repository, so new docs land in the right
place and read consistently.

## Where each kind of doc goes

| Kind | Location | When to use |
|---|---|---|
| **Package/component overview** | `<component>/README.md` | Every top-level component has one (see the template below). |
| **Architecture Decision Record** | `docs/decisions/NNNN-*.md` | A decision with lasting consequences and trade-offs. Immutable; supersede rather than edit. See [decisions/README.md](decisions/README.md). |
| **Spike** | `docs/<topic>-spike.md` | A reversible-adoption experiment documenting a pattern (e.g. an SDK-optional seam). |
| **Runbook** | `docs/<topic>-runbook.md` | Operational "how to run/read X" instructions. |
| **Plan** | `docs/plans/<topic>/{PLAN.md,REVIEW.md}` | A cross-cutting execution plan and its review. |
| **Gap analysis / audit** | `docs/gap-analysis-<date>*.md` | A measured baseline and remediation record. |
| **Charter** | `docs/CHARTER.md` | The north-star scope & invariants. Changes rarely, by deliberate decision. |

When in doubt: a *decision* is an ADR; a *how-to* is a runbook; a *plan of work*
is a plan; an *overview of a thing that exists* is a README.

## Naming conventions

- **`UPPERCASE.md`** is reserved for standard/community-health files at the repo
  root: `README`, `LICENSE`, `NOTICE`, `CHANGELOG`, `CONTRIBUTING`, `SECURITY`,
  `CODE_OF_CONDUCT`, `SUPPORT`, `GOVERNANCE`, `MAINTAINERS`, `AGENTS`,
  `HARNESS_SPEC`, `NEXT_STEPS`. Per-package `CHANGELOG.md` / `GAP_ANALYSIS.md`
  follow the same rule.
- **`progress.md`** stays lowercase — it is a running work log, not a standard
  file, and rotates into `progress-archive/`.
- **Other docs** use `kebab-case.md` (e.g. `e2e-runbook.md`, `phoenix-spike.md`).
  Existing snake_case names (`c4_architecture.md`) are kept as-is to avoid link
  churn; new docs should be kebab-case.
- **Directories:** multi-word component dirs are kebab-case (`agent-core`); the
  Python package inside is snake_case (`agent_core`). This dual convention is
  intentional and repo-wide.

> Do not move or rename `HARNESS_SPEC.md` / `NEXT_STEPS.md` (referenced by
> `AGENTS.md`, `docs/CHARTER.md`, and tooling) without updating every reference —
> grep first.

## Component README template

Every top-level component README follows this skeleton:

```markdown
# <name>

> One-line purpose.

Short paragraph: what it is and why this scope.

## What's in it        (map of modules/areas — a table is good)
## Install & use        (install command + a minimal usage example)
## Test                 (the exact command + the coverage floor)
## Links                (CHANGELOG / GAP_ANALYSIS / relevant ADRs / root docs)
```

Keep it scannable. Link to authoritative sources (the root README, the charter,
ADRs) rather than restating them.

## Prose formatting

- Prefer tables and short sections over long prose walls.
- Cross-link with **relative** paths so links work on GitHub and in the mkdocs
  site.
- Fenced code blocks get a language tag.
- Mermaid diagrams use a fenced code block tagged `mermaid` (the site enables
  `pymdownx.superfences`).

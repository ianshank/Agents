# PLAN — Enterprise Documentation & Repository Organization Overhaul

> Spec-driven execution plan for Claude Code. **Scope: documentation, repository
> organization, and package metadata only.** No runtime logic, gate thresholds,
> scorers, judges, or `features.yaml` semantics change. The only code-adjacent
> edits are declarative `pyproject.toml` metadata and a docs-only `mkdocs`
> dev-extra.
>
> Status: **PR 1 (Batch A + B) shipped on
> `claude/readme-docs-enterprise-update-d3ifmr`.** PR 2 (Batch C, protected paths)
> is outstanding. See [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) for the measured
> done/deferred/open breakdown.

## Locked decisions (maintainer)

1. **License: Apache-2.0** — permissive with an explicit patent grant.
2. **Audience: hybrid** — internally stewarded, externally visible. Community-health
   files address external readers; governance stays with the core team.
3. **Docs delivery: a rendered `mkdocs-material` site** built from `docs/`
   (Markdown stays readable on GitHub).

## Guardrails

- No eval-semantic changes: `features.yaml`, `config/*` values,
  `src/eval_harness/{gating,scorers,judges}/`, thresholds are untouched.
- Protected paths (`scripts/eval_protected_paths.py` + CODEOWNERS): `.github/**`,
  `config/**`, `tests/**`, `scripts/validations/**`, gating/scorers/judges — need
  the `eval-change-approved` label; isolated into PR 2.
- Do not renumber ADRs (the `0007` gap is intentional) or hand-edit
  `architecture.mmd`.
- Do not add a `dependencies` array to `agent-core/pyproject.toml` (F-032).
- No new runtime dependencies; mkdocs is a docs-only dev extra.

## PR 1 — Docs + packaging metadata (UNPROTECTED) — SHIPPED

- **Licensing:** root `LICENSE` (Apache-2.0) + `NOTICE`; a `LICENSE` copy in each
  sub-package wheel.
- **Metadata (PEP 639) on all 7 pyprojects:** `license = "Apache-2.0"` (SPDX) +
  `license-files`, `readme`, `classifiers`, `[project.urls]`; `build-system`
  bumped to `setuptools>=77` (the SPDX expression requires it; a `License ::`
  classifier is intentionally omitted). Verified via isolated `pip wheel`.
- **Community-health (root):** `CONTRIBUTING`, `SECURITY`, `CODE_OF_CONDUCT`,
  `SUPPORT`, `GOVERNANCE`, `MAINTAINERS` — deferring to `docs/CHARTER.md`.
- **Component READMEs:** `flow-corpus`, `flow-protocol`, `skills`, `scripts`,
  `experiments`, `src/eval_harness`; `behavioral-regression/CHANGELOG.md`;
  clarified the `claude-foundation` staging notice (ADR 0017).
- **docs/ IA + site:** `docs/README.md`, `docs/decisions/README.md` (notes the
  0007 gap), `docs/STYLE.md`, `mkdocs.yml` + a root `[docs]` extra. Shipped
  **non-strict** — the corpus cross-links outside `docs_dir`.
- **Restructure:** additive root `README.md` (badges/TOC/monorepo map/docs
  section); `AGENTS.md` root-doc map extended; `CHANGELOG` dev entry.

## PR 2 — CI + doc guards (PROTECTED — requires `eval-change-approved`) — TODO

- `.github/ISSUE_TEMPLATE/*` + `.github/pull_request_template.md` mirroring the
  real gates.
- `.github/workflows/docs.yml` — `mkdocs build` (non-strict first), optional Pages
  deploy; reuse the `.github/actions/run-quality-gate` pattern.
- Doc-quality checks as **`docs.yml` steps** (markdownlint, link-check, "every
  component has a README", "every package declares license+urls") — not
  `scripts/*.py` (avoids the ≥85% scripts floor + protected `tests/**`).
- `config/README.md` (protected `config/**`) and a CODEOWNERS docs-path review.
- Optional: `docs/licenses.md` (optional-SDK license posture), then promote mkdocs
  to `--strict` once the link graph is inside `docs_dir`.

## Verification (of PR 1, all passing)

1. `pip wheel` (isolated) for root + `flow-protocol` → `License-Expression:
   Apache-2.0`, `License-File`, URLs, classifiers.
2. `mkdocs build` renders the site (non-strict).
3. `scripts/check_protected_changes.py --base-ref origin/main` → clean.
4. `agent-core` has no `[project].dependencies` (F-032 intact).
5. 0 broken relative links across the changed markdown.

## Non-goals

- No evaluation logic / gate / `features.yaml` changes.
- No ADR renumbering (only an index).
- No relocation of root meta-docs without a reference-updated decision.
- No `--strict` mkdocs gate on the first pass.

# PLAN — Enterprise Documentation & Repository Organization Overhaul

> Spec-driven execution plan for Claude Code. **Scope: documentation, repository
> organization, and package metadata only.** No runtime logic, gate thresholds,
> scorers, judges, or evaluation semantics change. The one code-adjacent edit is
> declarative package metadata (`[project]` license / URLs / classifiers /
> `readme`) in `pyproject.toml` files — no behavior changes.
>
> This plan brings a technically mature monorepo up to the *documentation and
> repository-hygiene* bar expected of an enterprise open-source / internal
> platform project. The engineering is already strong; the gap is discoverability,
> onboarding, governance, and consistency — not capability.
>
> **Protected-path note:** anything under `.github/**` (issue/PR templates,
> CODEOWNERS) and any new `tests/**` file is guarded by
> `scripts/check_protected_changes.py` and requires the `eval-change-approved`
> label. Those items are called out per phase and are sequenced so the
> unprotected, high-value work (root standard files, README, per-package docs)
> can land first without a label.

---

## 0. Ground Truth (verified against the codebase, 2026-07-24)

### What already exists and is strong
- **Root `README.md`** (≈320 lines): thorough — requirements→mechanism table,
  install, env vars, run, extend, quality gates, security scanning, layout,
  CI. Enterprise-grade content; the gap is *structure/navigation*, not depth.
- **Architecture**: `architecture.mmd` (generated import-edge view) +
  `architecture.yaml` (manifest) + `docs/c4_architecture.md` (hand-maintained
  C4 context/container/L3). Drift-gated in CI.
- **Governance-adjacent**: `docs/CHARTER.md` (vision/mission/scope/invariants),
  `AGENTS.md` (agent orientation), `HARNESS_SPEC.md` (canonical spec),
  `.github/CODEOWNERS`, 24 ADRs under `docs/decisions/` (intentionally
  non-contiguous — `0007` is a deliberate gap; do **not** renumber).
- **Change history**: root `CHANGELOG.md` (keep-a-changelog) plus per-package
  `CHANGELOG.md` in `agent-core/`, `behavioral-regression/`, `flow-corpus/`,
  `flow-protocol/`, `claude-foundation/`.
- **CI**: 15 workflows under `.github/workflows/` (per-package gates,
  architecture-drift, calibrated-merge-gate, etc.).
- **Existing READMEs**: root, `agent-core/`, `behavioral-regression/`,
  `claude-foundation/`, `demo/`, `experiments/backend-validation/`.
- **Existing convention for plans**: `docs/plans/<name>/{PLAN.md,REVIEW.md}`
  (this document follows it).

### The monorepo at a glance (5 packages + skills + tooling)
| Path | Package name | Role |
|---|---|---|
| `src/eval_harness/` | `langfuse-eval-harness` | LLM evaluation harness (root) |
| `agent-core/` | `agent-core` | Deterministic control & calibration core |
| `behavioral-regression/` | `behavioral-regression` | ship/hold/escalate regression gate |
| `flow-corpus/` | `flow-corpus` | Calibration corpus of agentic flow variants |
| `flow-protocol/` | `flow-protocol` | Versioned contract between corpus and harness |
| `claude-foundation/` | `claude-foundation-tools` | Foundation Claude Code plugin tooling |
| `skills/` | (registry) | Vendored skills indexed by `marketplace.yaml` |
| `scripts/` | (tooling) | Feature validators + CI guards |
| `experiments/` | (isolated) | Temporary, gated experiments |

### Enterprise documentation gaps (the actual work)
1. **No `LICENSE`** anywhere in the repo, and **no `license` / `classifiers` /
   `[project.urls]`** in any `pyproject.toml`. This is the single most important
   enterprise gap — legal ambiguity blocks adoption/redistribution.
2. **No repo-root community-health files**: `CONTRIBUTING.md` (only
   `agent-core/` has one), `SECURITY.md`, `CODE_OF_CONDUCT.md`, `SUPPORT.md`,
   `GOVERNANCE.md`, `MAINTAINERS.md`/`AUTHORS`.
3. **No `.github/` issue templates or PR template** (`ISSUE_TEMPLATE/`,
   `pull_request_template.md`). *(Protected path.)*
4. **Missing component READMEs**: `flow-corpus/`, `flow-protocol/`, `skills/`,
   `config/`, and a top-level `experiments/` README (only its
   `backend-validation/` sub-experiment is documented). `scripts/` has no README
   (only the layout blurb in the root README).
5. **No `docs/` index**: `docs/` holds 40 files (ADRs, spikes, gap-analyses,
   runbooks, templates, charter) with **no `docs/README.md`** mapping them. Hard
   to navigate; no documented taxonomy.
6. **Root meta-doc sprawl**: `AGENTS.md`, `HARNESS_SPEC.md`, `NEXT_STEPS.md`,
   `progress.md`, `CHARTER.md` (in docs), `NEXT_STEPS.md` — six overlapping
   "what/why/next" docs. A reader has no single entry point telling them which to
   read. (`AGENTS.md` §"Root documentation map" partly does this; it should be
   surfaced from the README and made the canonical map.)
7. **README lacks enterprise navigation scaffolding**: no badges (CI, coverage,
   license, Python versions), no table of contents, no top-of-file "what is this
   / who is it for / monorepo map" section before the deep requirements table.
8. **Naming/style inconsistency**: mix of `UPPERCASE.md` (AGENTS, CHANGELOG,
   HARNESS_SPEC, NEXT_STEPS) vs lowercase (`progress.md`), kebab-case dirs vs
   snake_case packages, `GAP_ANALYSIS.md` per package with no shared template.
9. **No documentation contribution/style guide** (how docs are structured, when
   an ADR vs a spike vs a runbook is warranted, doc lint rules).
10. **No docs quality automation**: no markdown link-check, no markdown lint, no
    "every package has a README" guard. Nothing prevents doc drift.

---

## 1. Objective & Definition of Done

**Objective:** a newcomer (engineer, evaluator, or security reviewer) can land on
the repo root, understand what the platform is and how it is organized within two
minutes, find the right doc for any question, install/run/contribute without
tribal knowledge, and see clear licensing and security-reporting policy — all
without any change to evaluation behavior or gate semantics.

**Definition of Done (plan level):**
1. **Licensing is unambiguous** — a root `LICENSE` exists and every
   `pyproject.toml` declares `license`, `[project.urls]`, and `classifiers`.
2. **Community-health set is complete** — root `CONTRIBUTING.md`, `SECURITY.md`,
   `CODE_OF_CONDUCT.md`, `SUPPORT.md`, `GOVERNANCE.md` exist and are consistent
   with the existing charter and CI reality.
3. **Every top-level component has a README** following one shared template
   (purpose, install, usage, test/gate command, links) — no orphan directories.
4. **`docs/` is navigable** — `docs/README.md` indexes every doc by category
   (architecture, decisions, runbooks, spikes, gap-analyses, templates, plans)
   and a documented taxonomy says where new docs go.
5. **The root README is enterprise-navigable** — badges, TOC, a "who is this
   for / monorepo map" section above the deep dive, cross-links to all package
   READMEs and the docs index. All existing depth is preserved.
6. **Package metadata is complete** — README rendering on PyPI-style tooling,
   URLs, and supported-Python classifiers present.
7. **Doc consistency is guarded** — at minimum a markdown link-check + a
   "component READMEs exist" check are wired into CI (advisory first), and a
   short `docs/STYLE.md` documents naming/structure conventions.
8. **No regression** — `make check-all` and the architecture-drift gate stay
   green; no protected eval-defining file changes without the label.

---

## 2. Guardrails (do not violate)

- **No evaluation-semantic changes.** Do not touch `features.yaml`, `config/*`
  (values), `src/eval_harness/{gating,scorers,judges}/`, or any gate threshold.
  Documentation may *describe* them.
- **Respect protected paths.** `.github/**` and new `tests/**` require the
  `eval-change-approved` label — batched into a clearly-marked phase.
- **Do not renumber ADRs** (0007 gap is intentional) or hand-edit
  `architecture.mmd` (regenerate from `architecture.yaml`).
- **Charter scope (§3) and invariants (§4)** in `docs/CHARTER.md` bound this
  work; documentation must reflect them, not expand them.
- **`validate_skill.py` drift guard** — if any doc change implies touching the
  vendored skill copies, re-sync all copies.
- **Preserve existing depth.** The README rewrite is *additive structure*, not a
  content cull. Move detail into linked docs rather than deleting it.

---

## 3. Workstreams (phased, sequenced to land value early and unblocked)

### Phase 1 — Licensing & package metadata (highest ROI, unblocked)
**Why first:** legal clarity gates all external adoption; small, self-contained.
- [ ] Add root `LICENSE` (confirm license choice with maintainer — see
      §Open Questions; default recommendation below).
- [ ] Add `license = {file = "LICENSE"}` (or SPDX string), `readme`,
      `[project.urls]` (Homepage, Repository, Changelog, Issues), and
      `classifiers` (License, Python 3.10–3.12, Intended Audience, Topic) to the
      root `pyproject.toml` and each package `pyproject.toml`
      (`agent-core`, `behavioral-regression`, `flow-corpus`, `flow-protocol`,
      `claude-foundation`).
- [ ] Verify each package's `readme` points at an existing README (creates a
      dependency on Phase 3 for the two packages lacking one).
- **Acceptance:** `python -m build --sdist` metadata (or `pip show`) shows
  license + URLs; no CI regression.

### Phase 2 — Root community-health files (unblocked)
- [ ] `CONTRIBUTING.md` (root) — dev loop, monorepo layout, per-package gate
      commands (`make check` / `make check-all`), TDD + coverage-floor
      expectations, protected-path rules, how to add a component/skill/ADR,
      commit/PR conventions. Generalize the excellent `agent-core/CONTRIBUTING.md`
      to the whole repo and link the per-package one for package specifics.
- [ ] `SECURITY.md` — supported versions, private reporting channel, disclosure
      policy, and how it relates to existing Snyk scanning + secret-scanning CI.
- [ ] `CODE_OF_CONDUCT.md` — Contributor Covenant (or org standard).
- [ ] `SUPPORT.md` — where to ask questions vs file issues; link docs index.
- [ ] `GOVERNANCE.md` — decision model (ADR process, charter authority,
      CODEOWNERS, protected-path approval). Reconcile with `docs/CHARTER.md`
      §6 (escalation) so there is one governance story.
- [ ] `MAINTAINERS.md` (or `AUTHORS`) — derived from `.github/CODEOWNERS` +
      `config/agent-authors.yaml`.
- **Acceptance:** GitHub "Insights → Community Standards" checklist is green for
  the items above; each file cross-links the canonical source, no duplication of
  charter content.

### Phase 3 — Per-component READMEs (unblocked; unblocks Phase 1 `readme=`)
Adopt one shared **README template** (extend `docs/SKILL_TEMPLATE.md` style):
`# name` · one-line purpose · why-this-scope · install/dev-from-here ·
usage/CLI · test & coverage-floor command · links (CHANGELOG, GAP_ANALYSIS,
ADRs, root docs). Then author/fill:
- [ ] `flow-corpus/README.md`
- [ ] `flow-protocol/README.md`
- [ ] `skills/README.md` — what the marketplace is, how `marketplace.yaml` +
      `marketplace.schema.json` work, how to add/validate a skill
      (`scripts/skill_marketplace.py`), the generator-skill distinction (ADR 0020),
      and a table of the registered skills.
- [ ] `config/README.md` — one row per YAML (`eval.example.yaml`,
      `nemotron_eval.yaml`, `lm_studio_eval.yaml`, `model_target.yaml`,
      `merge-gate-domains.yaml`, `agent-authors.yaml`, `agent-confidence.yaml`,
      `legacy.v0_9.yaml`) with purpose + which feature/gate consumes it.
- [ ] `scripts/README.md` — promote the root-README `scripts/` layout blurb into
      a real index (validators, CI guards, merge-gate seeding, e2e harness).
- [ ] `experiments/README.md` (top level) — what an "experiment" is, lifecycle,
      why it's outside `make check-all`, link to `backend-validation/`.
- [ ] Audit existing package READMEs (`agent-core`, `behavioral-regression`,
      `claude-foundation`, `demo`) against the template for parity (badges,
      "run from here", links) — light touch, keep their content.
- **Acceptance:** every top-level directory that ships code or config has a
  README; all follow the same section skeleton.

### Phase 4 — `docs/` information architecture (unblocked)
- [ ] `docs/README.md` — the documentation index/map: categorized links to
      architecture (`c4_architecture.md`, root `architecture.*`), **Decisions**
      (ADR list with titles + the 0007-gap note), **Runbooks**
      (`e2e-runbook.md`), **Spikes** (`phoenix-spike.md`, `braintrust-spike.md`),
      **Gap analyses**, **Templates** (`SKILL_TEMPLATE.md`,
      `SKILL_VALIDATION_TEMPLATE.md`), **Charter**, **Plans**. Mirror the
      `AGENTS.md` "root documentation map" so humans and agents share one map.
- [ ] `docs/decisions/README.md` — ADR index with status column + link to a copy
      of the ADR template; document the numbering/gap convention.
- [ ] `docs/STYLE.md` — documentation style & taxonomy guide: when to write an
      ADR vs spike vs runbook vs plan; naming conventions (see Phase 6); the
      shared README template; markdown lint rules.
- **Acceptance:** from `docs/README.md` a reader reaches any of the 40 docs in
  one hop; taxonomy is written down.

### Phase 5 — Root README enterprise restructure (unblocked; do after 3 & 4 exist to link)
Additive structure only — **preserve all current content**, relocating deep
detail into the now-existing linked docs where it bloats the top:
- [ ] Add a header block: project name, one-line value prop, **badges** (CI
      status per key workflow, license, Python 3.10–3.12, coverage floor —
      shields that don't require secrets), and a one-paragraph "what/who".
- [ ] Add a **Table of Contents**.
- [ ] Add a **"Monorepo map"** section near the top (the at-a-glance package
      table from §0 here) linking each package README — before the deep
      requirements→mechanism table.
- [ ] Add a **"Documentation"** section linking `docs/README.md`, `CONTRIBUTING`,
      `SECURITY`, `CHARTER`, `AGENTS.md`, ADRs.
- [ ] Keep the existing Install/Env/Run/Extend/Quality-Gates/Layout/CI sections;
      trim only where a link now carries the detail.
- **Acceptance:** README opens with orientation, not a 3-level requirements
  table; every package and top-level doc is reachable from it; nothing
  previously documented is lost.

### Phase 6 — Naming & structure consistency (low risk, mostly docs)
- [ ] Document the convention in `docs/STYLE.md`: `UPPERCASE.md` reserved for
      community-health/standard files (README, LICENSE, CHANGELOG, CONTRIBUTING,
      SECURITY, CODE_OF_CONDUCT, GOVERNANCE, AGENTS); everything else
      kebab-case. Decide `progress.md` (keep lowercase as a log) and whether
      `HARNESS_SPEC.md`/`NEXT_STEPS.md` stay at root or move under `docs/`
      with root stubs — **document the decision; do not silently move** (these
      are referenced by `AGENTS.md`, `CHARTER.md`, and possibly CI).
- [ ] Standardize per-package `GAP_ANALYSIS.md` around one heading skeleton
      (documentation-only; content untouched).
- **Acceptance:** conventions are written and the root file set conforms or has a
  documented, referenced exception. **No file moves without updating every
  referencing doc/script** (grep first).

### Phase 7 — Protected-path items (needs `eval-change-approved` label; batch last)
- [ ] `.github/ISSUE_TEMPLATE/` — bug report, feature request, ADR proposal,
      security (redirect to `SECURITY.md`), + `config.yml`.
- [ ] `.github/pull_request_template.md` — checklist mirroring the real gates
      (tests/coverage floor, ruff/mypy, CHANGELOG entry, ADR-if-architectural,
      protected-path label reminder, docs updated).
- [ ] Review `.github/CODEOWNERS` for docs paths.
- **Acceptance:** templates render on new issues/PRs; landed under one labeled
  PR; no gate logic touched.

### Phase 8 — Documentation quality automation (advisory → enforcing)
- [ ] Add a markdown **link-checker** (e.g. lychee/markdown-link-check) as an
      advisory CI job first.
- [ ] Add a **"every top-level component has a README"** + "every package
      `pyproject` declares license/urls" check (a small `scripts/` guard, mirrors
      the existing validator style; adding it under `scripts/validations/` or a
      new `tests/` file is **protected** — sequence with Phase 7).
- [ ] Optional: markdownlint config for the documented style.
- [ ] Optional (separate decision): a docs-site generator (`mkdocs-material`)
      over `docs/` — **out of scope unless requested**; noted for the roadmap.
- **Acceptance:** doc drift (dead links, missing README, missing license) is
  caught by CI; enforcing mode enabled once green.

---

## 4. Deliverables checklist

| # | Deliverable | Path | Phase | Protected? |
|---|---|---|---|---|
| 1 | License | `LICENSE` | 1 | no |
| 2 | Package metadata (license/urls/classifiers) | all `pyproject.toml` | 1 | no |
| 3 | Contributing guide | `CONTRIBUTING.md` | 2 | no |
| 4 | Security policy | `SECURITY.md` | 2 | no |
| 5 | Code of conduct | `CODE_OF_CONDUCT.md` | 2 | no |
| 6 | Support guide | `SUPPORT.md` | 2 | no |
| 7 | Governance | `GOVERNANCE.md` | 2 | no |
| 8 | Maintainers | `MAINTAINERS.md` | 2 | no |
| 9 | Component READMEs | `flow-corpus/`, `flow-protocol/`, `skills/`, `config/`, `scripts/`, `experiments/` | 3 | no |
| 10 | Docs index + ADR index + style guide | `docs/README.md`, `docs/decisions/README.md`, `docs/STYLE.md` | 4 | no |
| 11 | README restructure | `README.md` | 5 | no |
| 12 | Naming conventions documented | `docs/STYLE.md` | 6 | no |
| 13 | Issue/PR templates | `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md` | 7 | **yes** |
| 14 | Docs CI (link-check, README/license guard) | `.github/workflows/`, `scripts/` | 8 | **yes** |

---

## 5. Sequencing, batching & effort

- **Batch A (one PR, unblocked, ~highest value):** Phase 1 + Phase 2 + Phase 3.
  Licensing, community-health, and the missing READMEs — no protected paths, no
  gate risk.
- **Batch B (one PR, unblocked):** Phase 4 + Phase 5 + Phase 6. Docs index,
  README restructure, and documented conventions — depends on Batch A existing so
  links resolve.
- **Batch C (one labeled PR):** Phase 7 + Phase 8. All protected-path
  (`.github/**`, `tests/**`) changes together, requesting `eval-change-approved`
  once.
- Each batch keeps `make check-all` and architecture-drift green; docs-only
  batches should not trip any code gate.

## 6. Non-goals (explicitly out of scope)

- No changes to evaluation logic, gate thresholds, scorers, judges, datasets, or
  `features.yaml`.
- No renumbering/rewriting of existing ADRs (only adding an index).
- No mass file relocation of root meta-docs without a documented decision and a
  full reference-update (Phase 6 documents the convention; moves are a separate,
  reviewed step).
- No public docs-site build (mkdocs/RTD) unless explicitly requested — noted as a
  roadmap option only.
- No new runtime dependencies.

## 7. Risks & mitigations

- **Protected-path CI block** → all `.github/**` / `tests/**` work isolated to
  Batch C with the label requested up front.
- **Link rot from restructure** → Phase 8 link-checker; also grep for inbound
  references before moving/renaming anything (Phase 6).
- **Duplication/drift between charter, AGENTS.md, and new governance docs** →
  new docs *link to* the charter as the single source of truth rather than
  restating it; the docs index mirrors the existing `AGENTS.md` map.
- **README bloat vs depth loss** → additive restructure with content relocated
  to linked docs, never deleted; reviewer diff shows moves, not removals.

## Open questions (need a maintainer decision before Phase 1/2)

1. **License choice** — Apache-2.0 (recommended for an enterprise platform with
   patent grant), MIT, or a proprietary/internal notice? No license file exists
   today, so this is a fresh decision.
2. **Public vs internal** — is this repo intended for external contributors
   (affects CODE_OF_CONDUCT enforcement contact, SECURITY reporting channel,
   SUPPORT venue) or internal-only?
3. **Root meta-doc placement** — keep `HARNESS_SPEC.md` / `NEXT_STEPS.md` at root
   (referenced by `AGENTS.md`/`CHARTER.md`) or relocate under `docs/` with
   stubs? Phase 6 will document whichever is chosen.
4. **Docs site** — is a rendered `mkdocs` site wanted now, or is in-repo Markdown
   sufficient (default assumption: in-repo Markdown)?

---

*This plan changes no evaluation behavior. It is the documentation- and
organization-layer counterpart to the engineering maturity already present in
the repo — see `docs/CHARTER.md` for scope authority and `AGENTS.md` for the
existing root-documentation map this plan formalizes.*

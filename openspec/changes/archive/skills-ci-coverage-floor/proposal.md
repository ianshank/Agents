# Change: skills-ci-coverage-floor

**Status:** landed — F-050 @ `c5e7227c6a` · **Date:** 2026-07-31 · **Author track:** `claude/` agent lane
**Motivated by:** an ROI review of `skills/` CI coverage, independently re-verified against
`.github/workflows/skills-ci.yml` and every other workflow's `paths:` filters
**Compiles down to:** F-050 + `scripts/validations/F_050.py` + ADR 0030.

## Why

`skills/` holds 11 registered skills. `skills-ci.yml` ran a dedicated lint/type/pytest job for
8 of them, gated by a `paths:` filter that listed only 7 — `dataset-lint` was omitted. No
other workflow triggered on `skills/**` at all. Verified across all 15 workflows in
`.github/workflows/`: nothing else fires on a `skills/`-only change.

For the four uncovered skills (`dataset-lint`, `hierarchical-recursive-brainstorm`,
`openspec-quality-plan`, `openspec-peer-review`), a PR touching only that skill ran no lint,
no mypy, no pytest, no `validate_skill.py`, no marketplace validation, and — the sharpest
edge — no `check_skill_script_drift.py`. Editing a vendored
`skills/*/scripts/validate_skill.py` copy, the exact drift that guard exists to catch
(`AGENTS.md`), triggered nothing.

The proof system has the same blind spot from the other side. `F_045.py` asserts
`dataset-lint` is registered in `marketplace.yaml` and tracked by the drift guard, but never
that CI actually runs on its changes — so the ledger reported F-045 green while the job it
describes was unreachable on its own PRs. And `skill_marketplace.py`'s `validate_registry`
walks registry → directory, so an *unregistered* skill directory is invisible to every
existing check; nothing walks the other direction.

`paths:` is workflow-scoped and no job in the file carries its own `if:`, so the per-skill
list never bought selectivity — a change to any *listed* skill already fanned out every job
(measured: 24 jobs, 471 job-seconds, 40s wall clock on a representative run). It only bought
omission risk, and it was exercised.

This is charter invariant §4.6 ("Quality gates are non-negotiable… the regression,
protected-path, drift, and size-budget gates stay green") failing open on a subset of a §3
in-scope surface. It expands no scope and relaxes no invariant, so no charter escalation
(§6) is required — it restores an invariant that was silently unenforced.

## What changes

- **Trigger.** `skills-ci.yml`'s `paths:` filter becomes a single `skills/**` glob, replacing
  the 7-entry per-skill list, for both `push` and `pull_request`.
- **`all-skills` job (new).** Discovers every `skills/*/` directory dynamically (never an
  allowlist) and runs, accumulating failures rather than short-circuiting: `validate_skill.py
  --tier structural` per skill, `skill_marketplace.py validate`, and
  `check_skill_script_drift.py`.
- **Registration + job-coverage guard (new, inline in the same job).** Asserts every
  `skills/*/` directory is registered in `marketplace.yaml` and either has a dedicated job in
  `skills-ci.yml` or is in a documented `EXEMPT` mapping. Each `EXEMPT` entry is re-checked
  against `evals/evals.json` so a stale exemption fails loudly instead of drifting silently.
- **ADR 0030.** Codifies two enforcement tiers: full lint/type/coverage for skills with real
  library code (unchanged, existing 8 jobs), structural + marketplace + drift for the
  template's existing "Subjective skills" class (`docs/SKILL_TEMPLATE.md` §5.B) — the three
  skills already self-declare this in their own `SKILL.md` §5; the ADR enforces it at the CI
  layer for the first time.
- **F-050 + `scripts/validations/F_050.py`.** Proof script, wired into
  `tests/test_validation_scripts.py`'s parametrize list and `quality-gates.yml`'s `--cov=`
  list so it is coverage-measured and part of the offline suite that runs on `.github/`-only
  edits, not merely smoke-tested by `scripts/validate.py --tier fast`.
- **Doc drift fixes.** `skills/README.md`'s registered-skills table lists 8 of 11 skills;
  `skills/README.md` and `scripts/skill_marketplace.py`'s docstring both claim marketplace
  validation runs "structural + behavioral" when it only calls `check_structural`.

## Scope / non-goals

- **Non-goal: behavioral evals or a 95% coverage floor for the three subjective skills.**
  ADR 0030 records structural-only as their permanent contract, not debt to pay down later.
- **Non-goal: rewiring the 8 existing per-skill jobs to the ADR 0021 (CI gate delegation)
  composite action.** That proposal (status: Proposed) is untouched; this change explicitly
  reconciles scope with it rather than overlapping it (ADR 0030, "Relationship to ADR 0021").
- **Non-goal: widening `quality-gates.yml`'s trigger to `skills/**`.** The two repo-level
  guards it already runs (`check_skill_script_drift.py`, and — read-only — the marketplace
  registry) instead run inside the new `all-skills` job, which is cheaper: `quality-gates.yml`
  installs the full dev extras and runs the regression gate.
- **Deferred:** a sweep of `openspec/README.md`'s "Current changes" list, which lists 1 of the
  3 change directories that exist on disk before this one is added — the same "exists but
  unregistered" failure class this change fixes, one level up, filed as a follow-on rather
  than fixed here to keep this change's diff scoped to its own capability.

## Impact

- **New F-ID:** F-050, `scripts/validations/F_050.py` as its offline proof.
- **Source touched:** `.github/workflows/skills-ci.yml`, `.github/workflows/quality-gates.yml`
  (one `--cov=F_050` addition), `tests/test_validation_scripts.py` (import + parametrize
  entry) — all protected paths (`scripts/eval_protected_paths.py`: `.github/**`, `tests/**`),
  so the PR carries `eval-change-approved`.
- **Decision-changing when live:** a skill directory added without a `marketplace.yaml` entry,
  or without either a dedicated job or an `EXEMPT` entry, now **fails closed** in `all-skills`
  — today it passes silently. That is the entire point of the change. No existing skill's own
  job, `SCHEMA_VERSION`, or registry alias changes.
- **Not touched:** the 8 existing per-skill jobs' lint/type/pytest/coverage steps; the
  `check_skill_script_drift.py`/`skill_marketplace.py` implementations themselves (reused,
  not modified — `check_skill_script_drift.py` already auto-discovers vendored copies).

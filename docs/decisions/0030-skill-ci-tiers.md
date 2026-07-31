# 0030 — Skill CI tiers: a structural floor for every skill, full gates only where there's code

- Status: **Accepted.**
- Date: 2026-07-31
- Related: `.github/workflows/skills-ci.yml`, `scripts/skill_marketplace.py`,
  `scripts/check_skill_script_drift.py`, `scripts/validations/F_050.py`,
  `docs/SKILL_TEMPLATE.md` §5, `openspec/changes/skills-ci-coverage-floor/`, ADR 0020
  (deterministic generator skills), ADR 0021 (CI gate delegation), ADR 0022 (determinism
  boundary for inference skills).

## Context

`skills-ci.yml` ran a dedicated lint/type/pytest/`validate_skill` job for 8 of the repo's 11
registered skills, gated by a `paths:` filter that listed only 7 of those 8 (`dataset-lint`
was omitted). No other workflow triggered on `skills/**` at all. The result: a PR touching
only `dataset-lint`, `hierarchical-recursive-brainstorm`, `openspec-quality-plan`, or
`openspec-peer-review` ran no lint, no mypy, no pytest, no `validate_skill.py`, no
marketplace validation, and — the sharpest edge — no `check_skill_script_drift.py`. Editing
one of those four skills' vendored `scripts/validate_skill.py` copy, the exact drift that
guard exists to catch, triggered nothing.

`paths:` is workflow-scoped and no job in the file carries its own `if:`, so the 7-entry list
never bought selectivity — a change to any *listed* skill already fanned out every job in the
file (measured on a representative run: 24 jobs, 471 job-seconds, 40s wall clock). The list
only bought omission risk, and it was exercised.

Two of the four uncovered skills (`hierarchical-recursive-brainstorm`, `openspec-quality-plan`,
`openspec-peer-review` — three, not two) have no dedicated job for a real reason: they ship no
library code, only the vendored `validate_skill.py` copy, no `evals/evals.json`, and no
`tests/`. This is not a new situation needing a new rule. `docs/SKILL_TEMPLATE.md` §5 already
names this exact category — branch **B, "Subjective skills"** ("writing style, tone, visual
design — outputs needing human judgment... structural only... self-check against explicit
criteria... can omit `evals/` entirely") — and both `openspec-quality-plan/SKILL.md` and
`openspec-peer-review/SKILL.md` open their own §5 with "**Subjective skill validation:** There
is no honest scripted gate for the quality of [this output]." What was missing was not the
classification — the skills already claim it about themselves — but its enforcement: nothing
made "this skill is subjective, structural tier is its complete contract" a CI-checked fact
rather than an unread comment in a `SKILL.md` file.

## Decision

1. **`skills-ci.yml` triggers on `skills/**` as a single glob**, replacing the per-skill
   `paths:` list. Self-maintaining by construction — a new skill directory is in scope the
   day it lands, with no second file to remember to edit.

2. **A new `all-skills` job gives every `skills/*/` directory a structural floor**,
   discovered dynamically (`skills/*/`, never an allowlist): `validate_skill.py --tier
   structural`, `skill_marketplace.py validate`, and `check_skill_script_drift.py`. This is
   the mechanism that makes the drift guard reachable on every skill's own changes — before
   this job it only ran when a PR happened to also touch `scripts/**` (via
   `quality-gates.yml`).

3. **Two enforcement tiers, not one job per skill and not structural-only for everyone.**
   Skills with real library code keep their existing dedicated job (lint + mypy + pytest at
   the 95% branch-coverage floor + `validate_skill.py --tier structural,behavioral`).
   Skills in the template's **"Subjective skills"** class get structural tier + marketplace
   registration + drift guard — via the shared `all-skills` job — as their *complete* CI
   contract. No behavioral evals, no coverage floor, because there is no library code and no
   artifact-producing output to grade against; `docs/SKILL_TEMPLATE.md` §5.B already says
   so. This ADR codifies that classification at the CI layer rather than inventing a new one.

4. **The classification is a declared, self-checking exemption, not a silent omission.** An
   inline guard in the same job enumerates the three subjective skills in a `EXEMPT =
   {name: reason}` mapping (structured on the `docs.yml` component-README guard's
   derived-list + documented-exemption idiom) and asserts every `skills/*/` directory either
   has a dedicated job or is in that mapping. Each `EXEMPT` entry is further re-checked
   against `evals/evals.json`: if an exempted skill later grows real evals and library code,
   the exemption goes stale and the guard fails rather than continuing to pass — the same
   "manual list silently drifts from reality" failure this ADR closes, recreated one level
   up, self-guarded against.

### Relationship to ADR 0021 (CI gate delegation)

ADR 0021 (status: Proposed) names `skills-ci.yml` and proposes each *existing per-skill* job
delegate its lint/type/test steps to a generated `quality-gate.sh`, the way the five package
CI workflows already do. That proposal is about the 8 skill-specific jobs and is untouched
here. The new `all-skills` job is a different kind of thing: a repo-level guard over the
*skill set itself* (which directories exist, are registered, and are covered), not a
per-skill quality gate over one skill's code. It has no generated gate to delegate to and
none is proposed — its steps are asserted inline, by design, permanently, not as a stage this
ADR expects ADR 0021 to later absorb. `scripts/validations/F_050.py` reflects this split
directly: it asserts the 8 existing jobs' internals (where ADR 0021 delegation is a live
future possibility) through `_common.ci_enforces`, but asserts the new job's own commands via
plain substring checks, since they are never delegated.

## Consequences

- Every one of the 11 registered skills now gets CI on its own changes; previously 4 did not.
- A skill directory added without a `marketplace.yaml` entry, or without either a dedicated
  job or an `EXEMPT` entry, now fails closed in `all-skills` — previously it passed silently.
  This is the one deliberate, decision-changing effect of this change; nothing about an
  existing green skill's own job changes.
- No behavioral-evals or coverage-floor debt is created for the three subjective skills —
  their contract was already structural-only by the template's own rule; this only makes it
  enforced.
- The `EXEMPT` mapping is a second declarative list alongside `marketplace.yaml`, but unlike
  the `paths:` list it replaces, it is actively self-checked (against `evals/evals.json`) and
  will fail loudly rather than silently outlive its own justification.

## Alternatives considered

- **One dedicated lint/type/pytest job per skill, including the three subjective ones** —
  rejected: there is no library code to lint or type-check, and authoring a test suite whose
  only subject is the vendored `validate_skill.py` copy tests nothing the drift guard doesn't
  already prove.
- **Structural tier only, for every skill, dropping the existing 95% coverage floor** —
  rejected: regresses real coverage on the 8 skills that do ship library code, to solve a
  problem (the three subjective skills' floor) that doesn't apply to them.
- **A bare `EXEMPT` set with no re-check** — rejected: it would recreate, for itself, the
  exact "list silently drifts from the directories it describes" failure this ADR exists to
  close. The `evals/evals.json` re-check was added specifically to avoid shipping a second
  version of the same bug one layer up.
- **Widen `quality-gates.yml`'s trigger to `skills/**`** instead of adding a new job — rejected:
  that workflow installs the full dev extras and runs the regression gate, materially more
  expensive per PR than re-running two near-stdlib commands in a dedicated job.

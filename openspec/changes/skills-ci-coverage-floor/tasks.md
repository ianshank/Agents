# Tasks: skills-ci-coverage-floor

Ordered per `./review.md`. Owners use the fleet contract in `openspec/AGENTS.md`.
`[P]` = protected path → needs `eval-change-approved` + CODEOWNERS. `.github/**` and
`tests/**` are both protected (`scripts/eval_protected_paths.py`), so every task touching
`skills-ci.yml`, `quality-gates.yml`, or `tests/test_validation_scripts.py` carries the
label; `features.yaml` + `scripts/validations/**` stay isolated in their own commit per the
`merge-gate-health-integrity` precedent.

## WS-A — Trigger: single `skills/**` glob [P]

- [x] Replace the 7-entry per-skill `paths:` list (both `push` and `pull_request`) in
      `skills-ci.yml` with `skills/**`.
- [x] Confirm the workflow YAML still parses and the job list is unchanged.
- **Gate:** `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/skills-ci.yml'))"`
      — clean parse, `jobs` keys unchanged from before this task.

## WS-B — `all-skills` job: structural + registry + drift [P]

- [x] New job, single Python 3.12 (structural tier is file parsing; a matrix buys nothing).
- [x] `rc=0; for d in skills/*/; do validate_skill.py --skill "$d" --tier structural || rc=1;
      done; exit $rc` — accumulates failures, never short-circuits.
- [x] `skill_marketplace.py validate` and `check_skill_script_drift.py` steps.
- [x] `jsonschema` installed explicitly (lean install silently no-ops the schema check —
      confirmed live).
- **Gate:** run the three commands locally against the current repo state; all exit 0.

## WS-C — Registration + job-coverage guard [P]

- [x] Inline Python step, structured on the `docs.yml` component-README guard's
      derived-list + `dict[name, reason]` `EXEMPT` idiom.
- [x] Asserts every `skills/*/` directory is registered in `marketplace.yaml` and has either
      a dedicated job or an `EXEMPT` entry.
- [x] Each `EXEMPT` entry re-checked against `evals/evals.json` so a stale exemption fails.
- [x] Mutation-tested: an unregistered, job-less skill directory fails (both arms); adding
      `evals/evals.json` to an `EXEMPT` skill fails (staleness arm).
- **Gate:** mutation checks 1–2 in `./review.md`'s Verification section pass (observed red,
      reverted).

## WS-D — OpenSpec package (this package)

- [x] `proposal.md`, `design.md`, `tasks.md`, `review.md`,
      `specs/skills-ci-coverage/spec.md`.
- [ ] Add this change to the "Current changes" list in `openspec/README.md`.
- **Gate:** every file this package links to resolves (no dangling reference).

## WS-E — ADR 0030 (unprotected — `docs/**` absent from `PROTECTED_PATTERNS`)

- [x] `docs/decisions/0030-skill-ci-tiers.md` + index row in `docs/decisions/README.md`.
- **Gate:** `python scripts/check_charter_drift.py` — every reference resolves.

## WS-F — Ledger [P]

- [x] `features.yaml`: F-050, `category: infrastructure`, `tier: fast`, one `verification`
      bullet per pinned invariant, each naming `F_050.py` as its proving artifact.
- [x] `scripts/validations/F_050.py`: offline, text-only, `_common.ci_enforces` scoped to
      the assertions that face real delegation ambiguity (none here — the new job's steps
      are asserted via plain substring checks, per ADR 0030's relationship to ADR 0021).
- [x] Wired into `tests/test_validation_scripts.py`'s `parametrize`/`ids` lists and
      `quality-gates.yml`'s `--cov=` list.
- [x] `CHANGELOG.md` entry under `[1.3.0-dev]` → `### Fixed`.
- **Gate:** `python scripts/validate.py --tier fast` and the quality-gate tooling coverage
      step (`quality-gates.yml`'s pytest invocation, `--cov-fail-under=85`) both green.

## WS-G — Doc drift fixes (unprotected)

- [x] `skills/README.md`: registered-skills table lists 8 of 11 skills; add the 3 missing
      rows.
- [x] `skills/README.md` and `scripts/skill_marketplace.py`'s docstring both claim
      marketplace validation runs "structural + behavioral"; correct to what
      `validate_registry` actually calls (`check_structural`).
- **Gate:** `python scripts/skill_marketplace.py validate` still exits 0 (doc-only change).

## Follow-on (separate change; not this one)

- [ ] Sweep `openspec/README.md`'s "Current changes" list for the remaining 2 pre-existing,
      unregistered change directories.
- [ ] Rewire the 8 existing per-skill jobs to the ADR 0021 (CI gate delegation) composite
      action once that proposal moves from Proposed to Accepted and gains a skill-shaped
      coverage-contract flag (F_037.py's check 2 already documents this as pending).

## Archive

- [ ] F-050 lands with `status: done` + `implemented_in:<sha>`; `scripts/validate.py --tier
      fast` green; full quality-gate green; then move this change under
      `openspec/changes/archive/`.

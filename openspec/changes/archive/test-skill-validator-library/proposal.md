# Change: test-skill-validator-library

**Status:** implemented · **Date:** 2026-08-17 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/orbital-drift-alignment/PLAN.md` Phase 3, itself motivated by a
file-by-file comparison against a sibling project, independently fact-checked claim-by-claim
against this repo's actual files rather than trusted.
**Compiles down to:** a new `skills/common/tests/` suite + a new `common` job in
`skills-ci.yml` + one `EXEMPT` entry removed. No new F-ID and no new ADR: this reclassifies
`common` within ADR 0030's existing two-tier framework (adding the third case it left
unnamed) rather than creating new governance.

## Why

`skills/common/skill_validator.py` is the grading engine every other skill's vendored
`scripts/validate_skill.py` copy imports from — frontmatter parsing, eval-assertion grading,
and `_run_eval`'s subprocess execution (shell-quoting, a python3-token rewrite, timeout
handling). It is real, load-bearing library code, not a subjective/judgment-call skill. It
has zero measured, gated coverage today: grepping `.github/workflows/skills-ci.yml` for
`skill_validator` returns nothing — not in any of the 9 dedicated per-skill jobs (none of
them touch this file), and not in the `all-skills` job either. It is not lint- or
mypy-checked as a standalone target anywhere.

It does have substantial *indirect* exercise already: `tests/test_validate_skill.py` at the
repo root has 19 test functions, all importing `from scripts.validate_skill import ...` — the
vendored CLI wrapper's re-export surface, not `skill_validator` directly. That is a real and
legitimate test suite, but it tests a different contract (the wrapper's CLI/re-export
behaviour), and measuring it confirms two concrete gaps:

- `grade_file_exists` (`skill_validator.py:268-279`) has no dedicated test anywhere. It is
  *executed* once, incidentally, as a side effect of `test_check_behavioral_errors`'s "only
  existence checks" case (`tests/test_validate_skill.py:208-221`) — but no test asserts its
  actual pass/fail behaviour, the way `test_grade_file_contains` does for its sibling grader.
- `_run_eval`'s real subprocess mechanics (`skill_validator.py:167-195`: the python3-token
  rewrite regex, `shlex.quote`-based shell-quoting of `sys.executable`, and timeout handling)
  are monkeypatched around, not exercised. `test_grade_idempotent`
  (`tests/test_validate_skill.py:103-119`) explicitly replaces `_run_eval` with a mock "to
  avoid pytest-cov emitting coverage warnings to subprocess stderr" — a reasonable choice for
  that file's own purpose (proving the wrapper's re-export contract), but it means the real
  subprocess path has never actually run under test.

Measuring `tests/test_validate_skill.py`'s coverage of `skill_validator.py` directly
(`pytest tests/test_validate_skill.py --cov=skill_validator --cov-branch`) confirms both gaps
and surfaces more: 84% line/branch coverage, 30 statements and 10 partial branches missed,
including `get_validator_module_path` (never called), two `parse_frontmatter` fallback-parser
branches (a YAML block that parses but isn't a mapping; a block that raises out of
`yaml.safe_load` entirely), `load_evals`'s invalid-JSON-syntax branch, `first_path_token`
(never called directly), `_check_eval_file_refs`'s warning body, three more real-timeout
branches (`grade_idempotent`, `grade_command_exit_zero`, `_exec`), `grade`'s
unknown-assertion-type branch, and two `_run_one_eval` branches (a setup that succeeds before
its run step, and a run step that itself times out).

Separately, `skills-ci.yml`'s `all-skills` job carries an `EXEMPT` dict listing 4 skills that
skip a dedicated lint/type/pytest job, each with a documented reason
(`docs/decisions/0030-skill-ci-tiers.md`). Three of the four
(`hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`) are
ADR 0030's deliberate "subjective skill" class — no library code, no honest scripted
correctness gate, structural tier is their complete and correct contract. This change does
not touch those three or their exemption; ADR 0030's classification for them stands. The
fourth, `common`, carries a *different* reason: "shared library (skill validator, utilities);
not a standalone skill; no evals/". That reason argues `common` isn't an end-to-end-task
skill (true, and irrelevant — it never claimed to be one), but it does not argue against
ordinary unit testing of library code, which is exactly what section above shows is missing.

## What changes

- **New `skills/common/tests/test_skill_validator.py`** (+ `conftest.py`), importing
  `skill_validator` directly rather than through the wrapper. Covers both confirmed gaps —
  `grade_file_exists` (present, absent, a relative-path-under-skill-dir case, and a
  path-traversal case that characterises, rather than changes, the current unsandboxed
  `os.path.join` behaviour) and `_run_eval`'s real mechanics, invoked for real rather than
  monkeypatched: the python3/python token rewrite and its word-boundary exclusions
  (`python.exe`, `/usr/bin/python`, `mypython3` must NOT rewrite), `shlex.quote`-based
  shell-quoting of a `sys.executable` path containing spaces and shell metacharacters (proved
  by a real wrapper interpreter placed at such a path), shell-quoted arguments with spaces
  and metacharacters surviving a real `shell=True` round trip, `stdin=DEVNULL` behaviour, and
  a real (not simulated) `subprocess.TimeoutExpired` — asserted, not assumed from the
  `except` clause's existence. The remaining measured gaps (see "Why") are also closed, since
  the `common` job's own 95% branch-coverage floor is measured standalone
  (`cd skills/common && pytest tests --cov=skill_validator`) and can only be met by covering
  the module's full surface independently of the root suite's contribution. Nothing in
  `tests/test_validate_skill.py` is duplicated; it stays exactly as it is.
- **New vendored `skills/common/scripts/validate_skill.py`**, a byte-identical copy of the
  canonical `scripts/validate_skill.py` (confirmed identical across all existing skill
  copies before vendoring), registered in `scripts/check_skill_script_drift.py`'s
  `TRACKED_DUPLICATES` so it stays drift-checked like every other copy — it was already
  auto-discovered and passing via that guard's dynamic-discovery fallback, but every other
  tracked copy is also explicitly listed, and this keeps that convention rather than being
  the one silent exception to it.
- **New `common` job in `skills-ci.yml`**: pinned ruff/mypy install → `ruff check` +
  `ruff format --check` on `skill_validator.py`/`__init__.py`/`tests` → `mypy` on
  `skill_validator.py`/`__init__.py` (matching the established convention, universal across
  all 9 existing per-skill jobs, that `tests/` is ruff-checked but not mypy-checked) →
  `pytest tests --cov=skill_validator --cov-branch --cov-fail-under=95` →
  `validate_skill.py --skill . --tier structural` — **structural tier only**, not
  `structural,behavioral` like the 9 existing per-skill jobs. `common` has no
  `evals/evals.json` and no end-to-end task of its own to run behaviorally: it *is* the
  grading engine, not a task that produces gradable output for it to grade against. An inline
  comment in the workflow names this as a third case ADR 0030 did not explicitly enumerate —
  real, tested library code, but no behavioral surface — distinct from both the ADR's "real
  library code" tier as literally written (which pairs library-code status with a behavioral
  task to grade) and its "subjective skill" tier (no library code at all).
- **Remove `common`'s entry from the `EXEMPT` dict** in the `all-skills` job. The other three
  entries, and the "Subjective skills" framing comment above them (now accurate again, since
  it no longer has to stretch to cover a non-subjective fourth entry) are untouched.
- **Addendum, file-disjoint:** `skills/openspec-quality-plan/SKILL.md` §5 strengthened from 2
  presence-only self-check criteria to 6 concrete ones, matching the depth of its two
  ADR-0030 subjective siblings (`hierarchical-recursive-brainstorm/SKILL.md` §5 has 5,
  `openspec-peer-review/SKILL.md` §5 has 4). Prose only — no `evals/`, no `tests/`; the ADR
  0030 exemption for this skill is correct and is not being revisited.

## Scope / non-goals

- **Non-goal: touching the three ADR-0030 "subjective skill" exemptions.**
  `hierarchical-recursive-brainstorm` and `openspec-peer-review` keep their `EXEMPT` entries
  and receive no new tests/evals — both already have adequately concrete §5 self-check
  criteria (see the addendum above for the one skill whose criteria this change does
  strengthen, and why the other two did not need it).
- **Non-goal: a new F-ID or ADR.** `docs/plans/orbital-drift-alignment/PLAN.md` Phase 3's own
  file table has no `features.yaml`/`scripts/validations/F_0NN.py` row, unlike Phase 1's
  equivalent table. `scripts/validations/F_050.py`'s `_EXEMPT_SKILLS` tuple already only
  names the three subjective skills, never `common` — this change exercises ADR 0030's
  existing registration + job-coverage guard mechanism as designed (a skill either has a
  dedicated job or a documented exemption; `common` is moving from the latter to the former),
  not creating a new governance surface for it to prove.
- **Non-goal: rewriting `_run_eval`'s subprocess mechanics.** This change tests the existing
  implementation; it does not alter the python3-token rewrite regex, the quoting strategy, or
  the timeout handling. The path-traversal case in `grade_file_exists` is characterised, not
  fixed — `evals.json` is repo-authored content, not adversarial input, so sandboxing it is a
  separate decision this change does not make.
- **Non-goal: `scripts/tool_versions.py`.** A parallel phase (`pin-lockstep-tool-versions`)
  adds this. The new `common` job hardcodes the current `ruff==0.15.20`/`mypy==2.1.0` pins
  (matching every other job in the file today) with a one-line comment marking the switch to
  make once that phase's branch merges.

## Impact

- **Source touched:** `skills/common/tests/test_skill_validator.py` (new),
  `skills/common/tests/conftest.py` (new), `skills/common/scripts/validate_skill.py` (new,
  vendored copy), `skills/common/ruff.toml` (new, matching every other vendoring skill's
  exclude-the-vendored-copy convention), `scripts/check_skill_script_drift.py`
  (`TRACKED_DUPLICATES` addition), `.github/workflows/skills-ci.yml` (new `common` job +
  one `EXEMPT` entry removed), `skills/openspec-quality-plan/SKILL.md` (§5 strengthened).
- **Protected paths:** `.github/**` is protected (`scripts/eval_protected_paths.py`), so the
  `skills-ci.yml` edits carry `eval-change-approved` + CODEOWNERS review. `tests/**` is
  protected too, but only matches the root suite (`^tests/.*$` once compiled) — the new
  `skills/common/tests/` directory is a distinct, unprotected path, matching every other
  skill's own `tests/` directory today.
- **Coverage measured, not assumed:** baseline (19 existing root tests, pointed at
  `skill_validator` directly) is 84% (227 statements, 30 missed; 94 branches, 10 partial).
  The new standalone suite (`cd skills/common && pytest tests --cov=skill_validator
  --cov-branch --cov-fail-under=95`) reaches 100% (0 missed statements, 0 partial branches),
  comfortably clearing the 95% floor every other library-shipping skill in this repo is held
  to.
- **Not touched:** `tests/test_validate_skill.py` (all 19 tests, unchanged), `skill_validator.py`
  itself (test-only change — no production-code edit), the three ADR-0030 subjective-skill
  `EXEMPT` entries, `docs/decisions/0030-skill-ci-tiers.md`.

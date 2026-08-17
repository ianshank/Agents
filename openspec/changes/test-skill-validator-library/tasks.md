# Tasks: test-skill-validator-library

`[P]` = protected path → needs `eval-change-approved` + CODEOWNERS review
(`scripts/eval_protected_paths.py`: `.github/**` is protected; `tests/**` is protected but
only matches the root suite once compiled — `skills/common/tests/**` is a distinct,
unprotected path, like every other skill's own `tests/`).
Coverage floor for this package: **95%** branch, matching every other library-shipping skill.

## WS-A — Direct unit tests for `skill_validator.py` (unprotected)

- [x] `skills/common/tests/conftest.py`: puts the skill root (not `scripts/`, since
      `skill_validator.py` lives at the skill root here) on `sys.path`.
- [x] `skills/common/tests/test_skill_validator.py`, importing `skill_validator` directly.
      Covers both confirmed gaps: `grade_file_exists` (present, absent, nested-relative-path,
      and a path-traversal case that documents current unsandboxed behaviour) and
      `_run_eval`'s real subprocess mechanics (python3/python token rewrite + word-boundary
      exclusions, `shlex.quote` shell-quoting of a `sys.executable` path containing spaces and
      shell metacharacters, shell-quoted-argument round trip, `stdin=DEVNULL`, and a real
      `subprocess.TimeoutExpired`) — invoked for real, not monkeypatched.
- [x] Every other gap surfaced by measuring the existing root suite's coverage of
      `skill_validator.py` directly is also closed: `get_validator_module_path`; the
      `parse_frontmatter` fallback parser's non-dict-YAML branch, exception branch, blank/`#`
      comment-line branch, and folded-continuation branch; `load_evals`'s invalid-JSON-syntax
      branch; `first_path_token` (direct tests, not only incidental exercise);
      `_check_eval_file_refs`'s warning body; `grade_idempotent`'s missing-`run_cmd` and
      real-timeout branches; `grade_output_contains`'s no-run branch;
      `grade_command_exit_zero`'s real-timeout branch; `grade`'s unknown-assertion-type
      branch; `_exec`'s real-timeout-to-`None` branch; `_run_one_eval`'s setup-real-timeout,
      setup-succeeds-then-run, `command_exit_zero`-only (no `run` key), and run-real-timeout
      branches; `check_behavioral`'s record-is-`None`-but-continues branch.
- [x] Nothing in the root `tests/test_validate_skill.py` (19 test functions) is duplicated or
      modified; it stays exactly as it is, testing the vendored wrapper's own contract.
- **Gate:** `cd skills/common && python -m pytest tests --cov=skill_validator --cov-branch
      --cov-fail-under=95 --cov-report=term-missing -q` — 100% branch coverage measured
      standalone (0 of 227 statements missed, 0 of 94 branches partial), ~8s wall clock.

## WS-B — Vendored wrapper + drift-guard registration (unprotected)

- [x] `skills/common/scripts/validate_skill.py`: byte-identical copy of the canonical
      `scripts/validate_skill.py` (confirmed via SHA-256/md5 equality against the canonical
      and against 2-3 other skills' copies before vendoring).
- [x] `skills/common/ruff.toml`: `extend = "../../pyproject.toml"` +
      `extend-exclude = ["scripts/validate_skill.py"]`, verbatim, matching every other
      vendoring skill's own `ruff.toml`.
- [x] `scripts/check_skill_script_drift.py`'s `TRACKED_DUPLICATES["scripts/validate_skill.py"]`
      gains the new copy's path (confirmed already passing via the guard's dynamic-discovery
      fallback *before* this explicit registration — added anyway, matching the convention
      every other tracked copy in the same tuple already follows).
- **Gate:** `python scripts/check_skill_script_drift.py` reports the new copy `"ok"`, not
      `"missing_copy"` or `"drift"`; `python -m pytest tests/test_skill_script_drift.py -q`
      (11 tests) still green.

## WS-C — CI wiring: new `common` job + `EXEMPT` cleanup [P]

- [x] New `common:` job in `.github/workflows/skills-ci.yml`, appended after
      `repo-invariant-review:` (the last existing per-skill job), matching the file's
      established per-skill job shape: checkout → setup-python (3.10/3.11/3.12 matrix) →
      pinned `pip install` → `ruff check` + `ruff format --check` on
      `skill_validator.py __init__.py tests` → `mypy --config-file ../../pyproject.toml
      skill_validator.py __init__.py` (tests excluded from mypy, matching the universal
      convention across all 9 existing jobs) → `pytest tests --cov=skill_validator
      --cov-branch --cov-report=term-missing --cov-fail-under=95` →
      `validate_skill.py --skill . --tier structural`.
- [x] `pip install` line carries `"pyyaml>=6"` explicitly — without it, `parse_frontmatter`'s
      YAML-success branch never executes in CI (the module degrades gracefully to its
      fallback parser when PyYAML is absent), silently failing the coverage floor even though
      every test assertion would still pass. See `design.md` for the full trace.
- [x] `ruff==0.15.20`/`mypy==2.1.0` hardcoded (matching every other job today) with a one-line
      comment marking the switch to `scripts/tool_versions.py`'s constants once the parallel
      `pin-lockstep-tool-versions` phase's branch merges — that file does not exist in this
      worktree yet.
- [x] **Structural tier only** (`--tier structural`, not `structural,behavioral`), with an
      inline comment explaining why: no `evals/evals.json`, no end-to-end task of its own —
      `common` is the grading engine, not a task for one to grade. Named explicitly as a third
      case ADR 0030 did not enumerate (real library code, no behavioral surface), distinct
      from both the ADR's library-code tier as literally written and its subjective-skill
      tier. Full reasoning in `design.md`.
- [x] `common` removed from the `all-skills` job's `EXEMPT` dict. The three ADR-0030
      subjective-skill entries (`hierarchical-recursive-brainstorm`, `openspec-quality-plan`,
      `openspec-peer-review`) and the "Subjective skills" framing comment above them are
      untouched.
- **Gate:** `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/skills-ci.yml'))"`
      clean parse; job list includes `common` (confirmed: `['eval-corpus-forge',
      'architecture-drift-guard', 'openai-judge', 'model-bench', 'project-setup',
      'quality-gate', 'deploy', 'dataset-lint', 'repo-invariant-review', 'common',
      'all-skills']`); `python scripts/validations/F_050.py` still passes unmodified (its
      `_EXEMPT_SKILLS` tuple never named `common`, only the three subjective skills); the
      `all-skills` job's registration + job-coverage guard logic, run locally against the
      edited files, reports `skill-coverage: OK - 13 skill(s) registered and CI-covered.`

## WS-D — Addendum, file-disjoint (unprotected)

- [x] `skills/openspec-quality-plan/SKILL.md` §5 strengthened from 2 presence-only criteria
      to 6 concrete ones (tooling named concretely, coverage target derived not boilerplate,
      configuration hardcode-free not just claimed, backwards-compatibility approach
      concrete, plus the original two), matching the depth of its two ADR-0030 subjective
      siblings. Prose only — no `evals/`, no `tests/` added; the ADR 0030 exemption for this
      skill is correct and untouched.
- **Gate:** `python scripts/validate_skill.py --skill skills/openspec-quality-plan --tier
      structural` still exits 0 (frontmatter untouched; only the §5 prose body changed).

## WS-E — OpenSpec package (this package)

- [x] `proposal.md`, `design.md`, `tasks.md`, `specs/skill-validator-coverage/spec.md`.
- [x] Add this change to the "Current changes" list in `openspec/README.md` (mechanically
      required — `docs.yml`'s OpenSpec-index check fails CI otherwise).
- **Gate:** every file this package links to resolves; no dangling reference.

## Verification

```bash
cd skills/common
python -m pytest tests --cov=skill_validator --cov-branch --cov-fail-under=95 --cov-report=term-missing -q
python -m ruff check skill_validator.py __init__.py tests
python -m ruff format --check skill_validator.py __init__.py tests
python -m mypy --config-file ../../pyproject.toml skill_validator.py __init__.py
python scripts/validate_skill.py --skill . --tier structural
cd ../..
python scripts/check_skill_script_drift.py
python scripts/skill_marketplace.py validate
python scripts/validations/F_050.py
python -m pytest tests/test_validate_skill.py tests/test_skill_script_drift.py -q
```

All eight commands run clean against the landed tree (see `design.md` and this session's
final report for the exact captured output).

## Archive

- [ ] This change merges into the orchestrating session's integration branch (this worktree's
      own job is implementation + local verification, not the merge itself). Once merged and
      confirmed green in CI, move this directory under `openspec/changes/archive/` per the
      house `openspec archive` convention — no F-ID to record (see `proposal.md`
      Scope/non-goals: this change claims none).

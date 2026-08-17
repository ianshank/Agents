# Design: test-skill-validator-library

## Placement

| Concern | Home | Why |
|---|---|---|
| Direct unit tests of `skill_validator.py` | `skills/common/tests/test_skill_validator.py` | Matches every other skill's own `tests/` layout (`skills/quality-gate/tests/`, `skills/dataset-lint/tests/`, …); the module under test lives at the skill root, not under `scripts/`, so `conftest.py` puts the skill root itself on `sys.path` rather than `<skill>/scripts` |
| Vendored CLI wrapper copy | `skills/common/scripts/validate_skill.py` | Same location every other skill vendors it at (`skills/<skill>/scripts/validate_skill.py`); `scripts/validate_skill.py`'s own upward directory search (`_CURRENT` climbs looking for a `skills/common/` sibling) works identically regardless of which skill's `scripts/` it starts from, so no special-casing is needed for `common` vendoring a copy of the wrapper that finds *itself* |
| CI job | new `common:` job in `.github/workflows/skills-ci.yml`, appended after `repo-invariant-review:` (the last existing per-skill job) and before the `all-skills:` job | Matches the file's existing job ordering (per-skill jobs, then the repo-level `all-skills` guard); no reordering of existing jobs |
| Lint exclusion for the vendored copy | `skills/common/ruff.toml` (new) | Every one of the 11 existing skills that vendors `validate_skill.py` carries this exact `extend = "../../pyproject.toml"` + `extend-exclude = ["scripts/validate_skill.py"]` file; without it, a repo-root `ruff check .` sweep (`scripts/quality-gate.sh`) would apply the *inherited* config to the vendored copy directly (ruff auto-discovers the nearest `ruff.toml` per file when no `--config` is passed) rather than treating its style as owned by the canonical source |

No `architecture.yaml` edit: this is test/CI infrastructure, not a new component or import edge.

## Coverage must be measured standalone, not borrowed from the root suite

The `common` job's gate is `cd skills/common && pytest tests --cov=skill_validator
--cov-branch --cov-fail-under=95`, run as an isolated CI step with
`working-directory: skills/common`. That means the 19 tests in the root
`tests/test_validate_skill.py` — which import `from scripts.validate_skill import ...`, a
different module path — contribute **nothing** to this job's coverage number; they run in a
separate job (the root package's own suite) that never executes as part of `common`'s job.

This is why `skills/common/tests/test_skill_validator.py` cannot be scoped to only the two
named gaps (`grade_file_exists`, `_run_eval` mechanics): reaching 95% branch coverage of
`skill_validator.py`, measured in total isolation, requires covering the module's entire
surface — `parse_frontmatter`, `load_evals`, `first_path_token`, `check_structural`, every
grader, `_validate_eval_shape`, `_run_one_eval`, `check_behavioral` — from scratch. The new
file's ~70 tests therefore cover the same *ground* the root suite's 19 tests cover, but
through a different contract (`skill_validator`'s own public/internal surface, called
directly) and organised independently — not copy-pasted bodies, and not a second copy of the
root file's test names or structure.

## Real subprocess calls, not monkeypatching — verified safe in this repo's CI shape

`tests/test_validate_skill.py::test_grade_idempotent` monkeypatches `_run_eval` specifically
"to avoid pytest-cov emitting coverage warnings to subprocess stderr." Before committing to
the opposite choice throughout the new suite, this was checked directly rather than assumed
away: a probe script ran `_run_eval` for real, both bare and under `pytest --cov=skill_validator
--cov-branch`, and diffed stdout/stderr against an uninstrumented run. No coverage-related
warning text appeared in either capture mode (`-s` or plain `-q`) with this repo's pinned
`pytest-cov` (7.1.0). The real-subprocess design is therefore not merely "the brief asked for
it" — it was verified not to reintroduce the noise the root suite's comment warns about, in
this exact pytest-cov version. If a future pytest-cov bump reintroduces subprocess-coverage
noise, the fix is contained to this one file's timeout-family tests, which already avoid `==`
equality on captured output in favour of substring assertions.

Real (not simulated) `subprocess.TimeoutExpired` is exercised via a genuinely slow child
process — `python3 -c "import time; time.sleep(3)"` under a `timeout=1` — rather than a mock
that raises the exception on request. Measured empirically before being pinned as the
suite's timeout/sleep pair: a 1s timeout against a 3s sleep raises at ~1.0-1.1s wall clock
regardless of the sleep target's length (`subprocess.run` kills at the timeout mark, it does
not wait out the sleep), so lengthening the sleep only adds safety margin against
interpreter-startup jitter on a loaded CI runner, not wall-clock cost. Six such tests exist
(`_run_eval` directly, `_exec`, `grade_idempotent`, `grade_command_exit_zero`, and two
`_run_one_eval` paths — setup timeout and run timeout); measured total suite wall time is
~8s, well inside the job's 20-minute timeout.

The `_run_eval` shell-quoting tests (`sys.executable` monkeypatched to a path containing a
space, and separately to one containing a single quote, `$`, and parentheses) place a real
wrapper shell script at that path and confirm it re-executes correctly end to end — proving
`shlex.quote`'s wrapping survives a real shell round trip, not just that the regex
substitution ran. The word-boundary exclusion tests (`python.exe`, `/usr/bin/python`,
`mypython3`, `python3.11` must **not** be rewritten) use `echo` and assert the literal input
text comes back unchanged: if the rewrite regex had incorrectly matched one of these
look-alikes, `echo`'s output would be a python executable path instead of the literal string,
making a wrong rewrite fail loudly rather than silently.

## `pyyaml` must be an explicit CI dependency — a correctness requirement, not a convenience

`parse_frontmatter`'s YAML path (`import yaml` inside a `try`, `except Exception: pass`
around it) is written to degrade gracefully when PyYAML is absent — that is why the 9
existing per-skill jobs that never install `pyyaml` still pass their own
`validate_skill.py --tier structural,behavioral` step; the fallback line-by-line parser
handles simple flat frontmatter identically to real YAML.

That graceful degradation is exactly the trap for this job's coverage number. If `pyyaml`
were *not* installed in the `common` job's environment, every `parse_frontmatter` call would
take the `except Exception: pass` branch unconditionally (a bare `import yaml` inside the
function raises `ModuleNotFoundError` immediately, before `yaml.safe_load` is ever reached),
and the module's real-YAML-success code path (`skill_validator.py:57-59`) would never execute
in *any* test — dropping coverage well under the 95% floor even though every test's
*assertions* would still pass, because the fallback parser happens to produce the same dict
for this suite's flat key/value fixtures. This was traced through deliberately, not
discovered by a red CI run: the `common` job's pip install line carries `"pyyaml>=6"`
explicitly, matching the three existing jobs (`eval-corpus-forge`, `architecture-drift-guard`,
`openai-judge`) that already install it for their own reasons.

## Structural tier only: the third case ADR 0030 left unnamed

ADR 0030 draws exactly two lines: skills with real library code get the full
lint/type/pytest/`validate_skill.py --tier structural,behavioral` job (8 skills at the ADR's
writing, 9 today after `repo-invariant-review` and `dataset-lint`), and skills in the
template's "Subjective skills" class (`docs/SKILL_TEMPLATE.md` §5.B) get structural tier
only, via the `EXEMPT` mapping, because they ship no library code and no artifact-producing
output to grade behaviorally.

`common` does not fit either line as written. It ships real, now fully tested library code —
disqualifying it from the "subjective skill" tier, whose entire premise is the *absence* of
gradable code. But it also has no `evals/evals.json` and no end-to-end task of its own: it
*is* the grading engine that every other skill's behavioral tier calls into, not a task that
produces output for a behavioral tier to grade. Running `validate_skill.py --skill . --tier
structural,behavioral` against `common` itself would either no-op (no evals file: behavioral
tier immediately errors "needs a parseable evals/evals.json") or require authoring a
fictitious "task" for a library to appear to perform, purely to have something to point a
behavioral eval at — manufactured surface, not gained coverage. The real behavioral proof
for this code already exists, at higher fidelity than a scripted eval could offer: the
`pytest --cov=skill_validator --cov-fail-under=95` step immediately above it in the same job,
exercising the actual functions with real assertions, including real subprocess calls.

The workflow's inline comment names this as a third case explicitly, rather than silently
picking the more convenient of the two existing lines: `common` is real code (unlike the
subjective tier) with no behavioral surface of its own (unlike the other library-shipping
skills' tier). This is a classification correction inside ADR 0030's existing framework, not
a new one — the same "either a dedicated job or a documented `EXEMPT` entry" mechanism the
ADR's registration guard already enforces just now resolves `common` to the first arm instead
of the second.

## Path traversal in `grade_file_exists`: characterised, not sandboxed

`grade_file_exists` joins `skill_dir` and the assertion's `path` via plain `os.path.join`,
with no containment check — a `path` value like `"../outside.txt"` resolves outside
`skill_dir` and `os.path.exists` happily reports on whatever it finds there. A dedicated test
(`test_grade_file_exists_path_traversal_is_not_sandboxed`) pins this as documented, observed
behaviour rather than leaving it as an unstated assumption. It is deliberately not changed:
`evals.json` is repo-authored content reviewed the same way any other source file is, not
input from an untrusted party, so adding a sandboxing check here is a separate, unrequested
design decision this change does not make. If that threat model ever changes, the test above
is the regression signal that would need to flip alongside the fix.

## `TRACKED_DUPLICATES`: explicit registration alongside an already-passing dynamic guard

`check_skill_script_drift.py`'s `_find_all_vendored_copies` already dynamically discovers any
`skills/<skill>/scripts/<canonical-name>.py` file and folds it into the tracked set regardless
of whether it is explicitly listed — confirmed directly: `check_skill_script_drift.py`
reported `skills/common/scripts/validate_skill.py` as `"ok"` *before* it was added to
`TRACKED_DUPLICATES`. Explicit registration is therefore not strictly load-bearing for
correctness today. It is added anyway, matching every one of the other 11 listed copies
(`repo-invariant-review`'s copy is the sole existing exception, predating this change and out
of scope here), so the declarative list stays the readable, documented source of truth the
module's own docstring describes ("Add an entry here whenever a script is intentionally
copied into a skill"), with dynamic discovery as its backstop rather than its only mechanism.

## What is reused, and what is not

**Reused unchanged:** `skill_validator.py` itself (test-only change, zero production-code
edits); the conftest.py `sys.path`-insertion pattern from `skills/dataset-lint/tests/` and
`skills/quality-gate/tests/` (adapted for this module living at the skill root rather than
under `scripts/`); the `ruff.toml` vendored-copy exclusion pattern, verbatim, from every
skill that already carries it; the `EXEMPT = {name: reason}` dict idiom and the
registration + job-coverage guard, both from ADR 0030 (only the dict's membership changes,
not its shape or the guard's logic); the pinned `ruff==0.15.20`/`mypy==2.1.0` versions every
other job in this file uses today.

**Not reused, deliberately:** the root suite's `monkeypatch.setattr(..., "_run_eval", ...)`
pattern for the subprocess-mechanics tests — the entire point of this change's coverage of
`_run_eval` is that it be exercised for real (see above). No new coverage-exclusion pattern,
`.coveragerc`, or per-skill `pyproject.toml` is introduced; like every other skill, `common`'s
`pytest --cov-fail-under=` is passed on the CLI, not read from a local config file.

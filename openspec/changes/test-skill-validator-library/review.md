# Review: test-skill-validator-library

**Reviewed:** independently, against the actual landed tree at `cf60f7e`
(`worktree-agent-a677e84000123bf93`), by an outside reviewer with no access to the
implementer's self-report — every claim below was re-derived from the tree itself, not
trusted. Two passes, dated separately: a mechanical fact-check of every falsifiable claim
(verdicts CONFIRMED / CORRECTED / REFUTED) and an adversarial pass that attacks the design
and the tests, with attacks verified by actually mutating `skill_validator.py` and running
the suite against the mutation — not by reasoning about it in the abstract. Refuted attacks
are recorded, not deleted. Method and format: `openspec/changes/add-panel-judge/review.md`.
Scope: `docs/plans/orbital-drift-alignment/PLAN.md` Phase 3
(`test-skill-validator-library`), which was present in this worktree at
`docs/plans/orbital-drift-alignment/PLAN.md` as expected — no need to fall back to
`7cdba73` on `claude/orbital-drift-agents-reuse-aely36`.

## Verdict

**APPROVE WITH FOLLOW-UPS.** Every load-bearing claim checked out. The coverage command
runs clean at 100% (227/227 statements, 94/94 branches) with 68 tests passing in ~7s;
`skill_validator.py` and `__init__.py` (and the canonical `scripts/validate_skill.py`) carry
a genuine zero diff against base `159460a`; the new `common` CI job and the `EXEMPT` dict
edit are syntactically valid and internally consistent, proven by actually executing the
`all-skills` job's reconciliation script against the landed tree rather than reading it and
assuming; the "real, not mocked" timeout claim survived the strongest test available —
deleting the `timeout=` kwarg from `_run_eval` and watching the flagship test wait out the
full 3-second sleep before correctly failing "DID NOT RAISE TimeoutExpired," which is
categorically impossible for a mocked test. The disclosed `tool_versions.py` gap is real,
matches the brief exactly (TODO comment present, correctly worded, correctly scoped), and is
not a defect. The `openspec-quality-plan/SKILL.md` §5 strengthening is substantively more
rigorous, not just longer. The "9-for-9 precedent" for linting-but-not-mypy-checking `tests/`
is real, confirmed by reading all 9 existing jobs directly.

Two minor, non-blocking items surfaced under adversarial pressure and are listed as
follow-ups, not blockers: one genuine (if narrow) test-quality gap in
`_eval_entries`'s outer type guard, found by mutation rather than by inspection; one
harmless off-by-one in `tasks.md`'s own self-reported command count. Neither touches
production code, neither affects the shipped behavior, and both are cheap to fix whenever
convenient.

---

## Pass 1 — mechanical fact-check (2026-08-17)

Every command below was executed directly against the worktree at `cf60f7e`, not read and
assumed.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | 68 new tests, all passing | **CONFIRMED** | `cd skills/common && python -m pytest tests -v` → `collected 68 items` ... `68 passed in 7.27s`. `tests/test_skill_validator.py` is a wholly new file (git diff stat: `+695` lines, no prior version). |
| 2 | ~100% coverage of `skill_validator.py`, floor 95% | **CONFIRMED, exactly** | `python -m pytest tests --cov=skill_validator --cov-branch --cov-fail-under=95 --cov-report=term-missing -q` → `skill_validator.py 227 0 94 0 100%` / `TOTAL 227 0 94 0 100%` / `Required test coverage of 95% reached. Total coverage: 100.00%`. No `# pragma: no cover` exclusions anywhere in either file — the 100% is earned, not carved out. |
| 3 | `skill_validator.py` and `__init__.py` are a test-only change — zero production-code diff | **CONFIRMED** | `git diff 159460a HEAD -- skills/common/skill_validator.py` and `-- skills/common/__init__.py` both produce empty output. |
| 4 | (corollary, not explicitly claimed but load-bearing for the vendoring story) the canonical `scripts/validate_skill.py` is also untouched | **CONFIRMED** | `git diff 159460a HEAD -- scripts/validate_skill.py` empty; `diff scripts/validate_skill.py skills/common/scripts/validate_skill.py` → identical, both 80 lines. |
| 5 | Real (not mocked) `_run_eval` subprocess mechanics, including a real 1s-timeout-vs-3s-sleep `TimeoutExpired` | **CONFIRMED** | See dedicated section below — timed at 1.21s wall clock (not instant), and confirmed by mutation: deleting the `timeout=` kwarg makes the test wait the full 3s and then fail. The only `monkeypatch` uses in the file (`test_skill_validator.py:316,331`) patch `sys.executable`'s value, not `subprocess.run` — the subprocess call itself is always real. |
| 6 | New `common` job in `skills-ci.yml` is syntactically valid | **CONFIRMED** | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/skills-ci.yml'))"` parses clean; job list includes `common` exactly once, alongside the 9 existing per-skill jobs and `all-skills`. |
| 7 | `EXEMPT` dict edit (removing `common`) is internally consistent with `all-skills`'s reconciliation logic | **CONFIRMED** | Extracted and ran the exact Python block from the `all-skills` job's "Every skill is registered and CI-covered" step against the real tree: `skill-coverage: OK - 13 skill(s) registered and CI-covered.`, exit 0. `common` is covered via `name in job_names` (it now has a dedicated job), not via `EXEMPT` — the intended reclassification. |
| 8 | `tool_versions.py` doesn't exist yet; the new job hardcodes `ruff==0.15.20`/`mypy==2.1.0` with a TODO comment | **CONFIRMED** | `scripts/tool_versions.py` does not exist in this worktree (confirmed absent). `.github/workflows/skills-ci.yml:320-321`: `# TODO(tool_versions): scripts/tool_versions.py (RUFF_VERSION/MYPY_VERSION) lands via a` / `# parallel phase; switch this pin to its constants once that phase merges into this branch.` — present, clearly worded, correctly scoped to the `common` job's own `pip install` line (`skills-ci.yml:322`). |
| 9 | Baseline: the 19 existing root-level tests give 84% standalone coverage of `skill_validator.py` (227 stmts/30 missed, 94 branches/10 partial) | **CONFIRMED, exactly** | `pytest tests/test_validate_skill.py --cov=skill_validator --cov-branch --cov-report=term-missing -q` (run from `skills/common`) → `skill_validator.py 227 30 94 10 84%`, matching `proposal.md`'s numbers to the statement. |
| 10 | Root suite (`tests/test_validate_skill.py`) has 19 test functions and is untouched | **CONFIRMED** | `grep -c "^def test_" tests/test_validate_skill.py` → `19`. `git diff 159460a HEAD -- tests/test_validate_skill.py` empty. Suite still passes standalone: `19 passed`. |
| 11 | Root suite's `test_grade_idempotent` really does monkeypatch `_run_eval` (substantiating the new file's "different contract" framing) | **CONFIRMED** | `tests/test_validate_skill.py:103-119`: `def test_grade_idempotent(monkeypatch): # Mock _run_eval to avoid pytest-cov emitting coverage warnings to subprocess stderr` ... `monkeypatch.setattr("scripts.validate_skill._run_eval", mock_run_eval)`. |
| 12 | Vendored copy registered in `check_skill_script_drift.py`'s `TRACKED_DUPLICATES`; drift guard passes | **CONFIRMED** | `git diff` on the script shows one line added: `"skills/common/scripts/validate_skill.py",` under the `validate_skill.py` tuple. `python scripts/check_skill_script_drift.py` → `skill-drift: OK - 17 copy/copies match their canonical source.` |
| 13 | `common` already registered in `skills/marketplace.yaml` (pre-existing, unaffected) | **CONFIRMED** | `skills/marketplace.yaml:9` has a `common` entry predating this change; `python scripts/skill_marketplace.py validate` → `Skill marketplace OK`. |
| 14 | `openspec/README.md` "Current changes" list gained an entry for this package | **CONFIRMED** | `git diff` shows a new bullet at `openspec/README.md:64-70` describing the change, status "proposed." |
| 15 | `scripts/validations/F_050.py`'s `_EXEMPT_SKILLS` tuple never named `common` (only the three subjective skills), so it needs no change and still passes | **CONFIRMED** | `scripts/validations/F_050.py:53-57` lists only `hierarchical-recursive-brainstorm`, `openspec-quality-plan`, `openspec-peer-review`. `python scripts/validations/F_050.py` → `F-050 passed`. |
| 16 | `tasks.md`'s full verification block ("eight commands") runs clean against the landed tree | **CORRECTED (trivial)** | All commands in the block *do* run clean — independently re-run one by one: pytest+cov (100%), `ruff check`, `ruff format --check`, `mypy`, `validate_skill.py --tier structural`, `check_skill_script_drift.py`, `skill_marketplace.py validate`, `F_050.py`, and the root `pytest tests/test_validate_skill.py tests/test_skill_script_drift.py` — all pass. But counting the non-`cd` lines in the block gives **nine** commands, not eight (`tasks.md:111-123`). The substance of the claim ("all clean") is true; the number in the prose is off by one. |
| 17 | `openspec-quality-plan/SKILL.md` §5 strengthened from 2 to 6 concrete criteria, matching sibling depth | **CONFIRMED** | See dedicated section below. |
| 18 | This change makes no production-code edit anywhere, only tests/CI/docs | **CONFIRMED** | Full diff stat (`git diff --stat 159460a HEAD`) touches only: `skills-ci.yml`, the plan doc, `openspec/README.md`, the four new OpenSpec-package files, `check_skill_script_drift.py` (+1 line), `skills/common/ruff.toml` (new), `skills/common/scripts/validate_skill.py` (new, vendored), `skills/common/tests/{conftest.py,test_skill_validator.py}` (new), `skills/openspec-quality-plan/SKILL.md`. No `.py` file under active production import paths changed behavior. |

### Real-timeout claim, verified directly

`tests/test_skill_validator.py:376-380`:

```python
def test_run_eval_real_timeout_raises_timeout_expired():
    with pytest.raises(subprocess.TimeoutExpired):
        _run_eval(_SLEEP_CMD, ".", _SHORT_TIMEOUT)
```

with `_SHORT_TIMEOUT = 1` and `_SLEEP_CMD = 'python3 -c "import time; time.sleep(3)"'`
(`test_skill_validator.py:55-56`). Run in isolation: `1 passed in 1.21s` (wall clock,
via `time pytest ... -k test_run_eval_real_timeout_raises_timeout_expired`). A mocked
timeout would return in single-digit milliseconds; 1.21s is consistent with a real child
process being spawned, running for ~1.0-1.1s, and killed by the OS/subprocess timeout
machinery — not simulated. Independently reconfirmed by mutation (see Pass 2).

### `openspec-quality-plan/SKILL.md` §5, before/after

Before (`git show 159460a:skills/openspec-quality-plan/SKILL.md`), 2 criteria:

```
1. **Mandatory Sections Present**: The "Code Hygiene & Quality Gates" section is present in `design.md`.
2. **Phase Gates Present**: Every phase in `tasks.md` ends with a hygiene/test gate.
```

After (`skills/openspec-quality-plan/SKILL.md:43-48`), 6 criteria — the original two
(#1 kept verbatim, #2 upgraded) plus four new ones:

```
2. **Tooling Named Concretely**: ... not a generic placeholder like "appropriate linters."
3. **Coverage Target Is Derived, Not Boilerplate**: ... not the same number copy-pasted
   unchanged from the last package generated.
4. **Configuration Is Hardcode-Free, Not Just Claimed**: ... not a generic "config is
   externalized" sentence.
5. **Backwards-Compatibility Approach Is Concrete**: ... not a placeholder claim.
6. **Phase Gates Are Concrete**: ... names the actual command to run ... not a vague
   mention of "testing."
```

Compared directly against its two ADR-0030 subjective siblings:
`hierarchical-recursive-brainstorm/SKILL.md` §5 has 5 numbered criteria,
`openspec-peer-review/SKILL.md` §5 has 4. The new 6-criteria version matches their style
(bold label + one concrete sentence) and depth. This is not padding: every one of the 4 new
criteria moves the bar from "is X present" to "is X specific/derived/non-boilerplate" —
each is independently falsifiable against a real `design.md`/`tasks.md` in a way the
original 2 presence-only checks were not (a package could satisfy "Phase Gates Present" with
a gate that just says "run tests," which criterion #6 alone now explicitly disallows).

### "9-for-9 precedent" for tests/ ruff-checked, not mypy-checked

Read all 9 existing per-skill jobs in `skills-ci.yml` directly (not sampled): every one
runs `ruff check <src> tests` / `ruff format --check <src> tests` but `mypy ... <src>`
**without** `tests` in the file list —

`eval-corpus-forge` (:51,54), `architecture-drift-guard` (:86,89), `openai-judge` (:120,123),
`model-bench` (:153,156), `project-setup` (:184,186), `quality-gate` (:212,214), `deploy`
(:240,242), `dataset-lint` (:266,268), `repo-invariant-review` (:295,297).

9 for 9, confirmed, not asserted. The new `common` job (`:326-329`) follows the identical
pattern: `ruff check skill_validator.py __init__.py tests` /
`mypy ... skill_validator.py __init__.py` (no `tests`). The "deviation" from the literal
brief (lint `tests/` too) is not a deviation from house convention — it *is* house
convention, universally.

---

## Pass 2 — adversarial (2026-08-17, run after Pass 1, same tree — no commits landed between passes)

Assume the design is wrong and the 100% coverage number is a symptom of assertion-light,
line-hunting tests. Attack it. Every attack below was verified by actually running code
against the real tree (mutating `skill_validator.py` locally, running the suite, then
restoring via `git checkout` / hash comparison before moving on — confirmed clean after
every mutation: `git status --porcelain` empty throughout).

### Attack A — "100% coverage is a red flag for over-fitted, assertion-light tests"

**Method:** picked candidate "least-obviously-necessary" tests, mentally identified the
naive/broken implementation each one is implicitly guarding against, then actually reverted
`skill_validator.py` to that broken form and re-ran the targeted test(s) — not a thought
experiment, a real mutation-and-rerun.

| Mutation | Target | Result |
|---|---|---|
| M-A | `get_validator_module_path`: `dirname` → `basename` | `test_get_validator_module_path_returns_this_files_directory` **fails** with a clear diff (`'skill_validator.py' == '/home/.../skills/common'`) |
| M-B | `grade()`: always label with `t`, ignore a custom `"text"` field | `test_grade_uses_text_field_as_label_when_present` **fails** (`'exit_zero' == 'custom label'`) |
| M-C | `first_path_token`: drop the `not tok.startswith("-")` guard | `test_first_path_token_empty_command_returns_none` **alone** still passes (see Refuted-but-noted below) — but `test_first_path_token_skips_flag_tokens_even_with_a_slash` in the same group **fails** (`'--path=/etc/foo' is None` → actual `'--path=/etc/foo'`) |
| M-D | `_run_eval`: delete the `timeout=timeout` kwarg entirely (no real enforcement) | `test_run_eval_real_timeout_raises_timeout_expired` **fails**, and takes **3.58s wall clock** to do it (waits out the real 3s sleep, then reports `Failed: DID NOT RAISE TimeoutExpired`) — this is the strongest possible proof the timeout test is real: a mocked test cannot be made to wait out a genuine child-process sleep by changing production code it never touches |
| M-E | `_eval_entries`: drop the outer `isinstance(evals, list)` guard | `test_check_structural_with_non_list_evals_value_does_not_crash` **still passes** — genuine gap, see Attack A-2 below |
| M-F | `_eval_entries`: keep the outer guard, drop the inner `isinstance(ev, dict)` per-entry filter | `test_check_behavioral_non_dict_eval_entries_are_ignored` **fails** with `AttributeError: 'str' object has no attribute 'get'` |

**Verdict on the general attack: REFUTED.** 5 of 6 mutations across 5 different functions
were caught, including the one the task specifically asked to stress (the real-timeout
test survived the strongest possible check — production code deletion, not reasoning). The
suite is not line-hunting; it is behaviorally sensitive to real regressions in the large
majority of the surface tested.

**One sub-attack survives, narrowed and confirmed (Attack A-2, minor):**
`test_check_structural_with_non_list_evals_value_does_not_crash`
(`test_skill_validator.py:256-264`) uses the fixture `{"evals": "oops"}`. A Python string is
iterable, so `[ev for ev in evals if isinstance(ev, dict)]` — the *unguarded* form —
produces `[]` for a string input by coincidence, identically to the guarded form. The test
cannot distinguish `_eval_entries` with the `isinstance(evals, list)` check present from
`_eval_entries` with it removed, **for this specific fixture value**. Grepping the whole
suite (`grep -n '"evals":' tests/test_skill_validator.py`) confirms no test anywhere uses a
genuinely non-iterable `evals` value (`null`, a number, `true`) — the value that would
actually crash (`TypeError: 'int' object is not iterable` etc.) without the guard, verified
directly:
```
evals = 42
[ev for ev in evals if isinstance(ev, dict)]   # TypeError: 'int' object is not iterable
```
This is real but narrow: it affects one branch of one internal helper, `evals.json` is
repo-authored content rather than adversarial input (the same threat model the suite's own
`grade_file_exists` path-traversal test explicitly invokes for a different function), and
the shipped implementation is correct — only this one test's power to catch a *future*
regression on that specific line is weaker than its "covered" status in the coverage report
implies. Not a blocker. Listed as a follow-up.

**Sub-attack on M-C, refuted but kept:** in isolation,
`test_first_path_token_empty_command_returns_none` does not catch the flag-guard removal —
but it was never meant to; it exists to prove the zero-iteration path (`cmd.split() == []`)
returns `None` rather than raising, a distinct behavior from the flag-exclusion case, which
its sibling test covers. Judged as adequate division of labor between two small tests, not
a gap.

### Attack B — "structural-only for `common` silently skips something that should be checked"

Confirmed no `evals/` directory exists anywhere under `skills/common/` (`find skills/common
-type f` lists no `evals/*`). Forced the question empirically rather than by inspection:
ran `python scripts/validate_skill.py --skill skills/common --tier structural,behavioral`
directly against the real tree. Result:
```
SKILL VALIDATION FAILED:
  - behavioral tier needs a parseable evals/evals.json
```
exit 1. So `structural,behavioral` is not merely "the design says structural-only is
fine" — it is not an available option at all without first fabricating an `evals.json` that
would test nothing beyond what the `pytest --cov=skill_validator --cov-fail-under=95` step
in the same job already proves at higher fidelity (real function calls, real subprocess
execution, real assertions, currently 100% branch coverage vs. a hand-rolled scripted eval
that could only assert on CLI-level behavior). Cross-check: every one of the 9 other
per-skill jobs that *does* run `structural,behavioral` is exercising `skill_validator.py`
transitively already, through their own vendored `validate_skill.py` wrapper — so `common`'s
integration behavior (does it work when called *as* a library from another skill's
behavioral run) is continuously exercised by 9 independent CI jobs, not orphaned. **Verdict:
REFUTED** — structural-only is the only coherent choice given no `evals/evals.json`, and it
does not silently skip anything; the alternative literally does not run.

### Attack C — "the §5 strengthening is more verbose, not more rigorous"

Already covered in Pass 1's dedicated section (old vs. new text quoted in full, compared
against both siblings). **Verdict: REFUTED** — each of the 4 new criteria adds an
independent, falsifiable dimension (named tooling, derived coverage target, hardcode-free
configuration claims, concrete backwards-compatibility approach) that the 2 presence-only
originals could not catch; word count grew because substance grew, not the reverse.

### Attack D — "the 9-for-9 precedent for linting `tests/` is asserted, not real"

Already covered in Pass 1's dedicated section (all 9 jobs read directly, line numbers
cited). **Verdict: REFUTED** — real, universal precedent, correctly followed by the new
`common` job.

### Attack E — "the CI job matrix (Python 3.10/3.11/3.12) might not actually work on versions this sandbox can't run"

This sandbox has only Python 3.11.15 available; 3.10 and 3.12 were not directly
executable here. **Not fully verifiable in this review environment** — flagged as a known
limitation of this review, not a refuted or confirmed claim. Mitigating factors: the new
job's steps (`ruff`, `mypy`, `pytest`, `validate_skill.py`) are byte-for-byte the same
command shapes already running successfully across the 3.10/3.11/3.12 matrix in all 9
existing per-skill jobs in the same file, and `skill_validator.py` uses no version-specific
syntax beyond `from __future__ import annotations` + PEP 604 unions, both already exercised
by the existing suite on the same matrix. Low residual risk, not investigated further —
real CI is the actual proof once this lands.

---

## Residual risk / follow-ups (non-blocking)

- **Attack A-2 (minor, test-quality):** add one more `evals.json` fixture in
  `test_skill_validator.py` with a genuinely non-iterable `evals` value (e.g.
  `{"evals": null}` or `{"evals": 42}`), so `_eval_entries`'s outer `isinstance(evals,
  list)` guard is actually behavior-tested rather than merely branch-covered. Cheap,
  optional, does not block merge — `evals.json` is repo-authored content, not adversarial
  input, so the exposure this would close is theoretical, not observed.
- **Pass 1, item 16 (trivial, doc-only):** `tasks.md`'s Verification section says "All
  eight commands run clean" but the fenced block lists nine non-`cd` commands. Every
  command genuinely is clean (independently re-verified); only the count in the prose is
  off by one. Fix whenever the file is next touched.
- **Attack E (informational):** the 3.10/3.12 legs of the new job's matrix were not
  independently exercised in this review sandbox (3.11 only was available). Low risk given
  the job is structurally identical to 9 already-green jobs on the same matrix; real CI on
  the actual PR is the definitive check.

None of the above touch production code, none reduce the measured 100% coverage or the 68
passing tests, and none require a design change — all are additive, optional polish.

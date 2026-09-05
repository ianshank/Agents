# Branch hygiene audit — `claude/openspec-agents-eval-framework-yvb2sy`

**Date:** 2026-09-05 · **Scope:** WS-1 (F-064), WS-2 (M8 breadth), WS-3 (F-065 / ADR 0043),
and the repository wiring those three touch. ~2,150 new lines of Python plus a 1.2 MB
generated corpus.

**Method.** Three parallel review passes (CI wiring and coverage gates; anti-patterns and
hygiene; test practice and edge cases), then every claim above SEV-3 re-verified **by
execution** in this checkout before being believed. Two agent claims were overstated and are
corrected below. Every fix landed here was negative-controlled: the fix was reverted and the
new test observed to fail.

**Findings 21-24 came from an automated review of the pull request, after this document was
first written**, and are kept in their own section for the same reason the corrections are
kept: an audit that silently absorbs what a reviewer caught reads as more complete than it
was. One of them (24) was in this audit's own raw output and was lost in consolidation.

---

## The finding that matters most

**A mutation score of 2.0 was reachable from a real target run, not a hand-built payload.**

The suite below is entirely ordinary — it uses keyword arguments, which any generated test
suite will — and it produced `normalized = 2/1` flowing straight into a gate rule that takes
the **mean across items**, where one out-of-range value silently moves the verdict for every
other item in the run.

```
evidence mutants: {'generated': 2, 'covered': 1, 'killed': 2}
normalized score from a REAL target run -> 2.0   passed = True
```

This is the same defect class the branch exists to remove — a number credited without the
evidence to support it — reintroduced inside the capability that measures it. Three
independent causes, each fixed at its own layer:

| Layer | Defect | Fix |
|---|---|---|
| Recorder | logged raw `args`, so `add(n=2, k=1)` looked like a call with no arguments | bind to the focal signature before recording |
| Target | `covered` counted from `differs_at` alone, so a killed mutant could be uncovered | a kill **is** coverage evidence; `killed <= covered` is now an invariant |
| Scorers | nothing bounded the output | `bounded_ratio` clamps to `[0,1]`, logs, and sets `clamped` in the verdict metadata |

Three shapes reached the clamp in practice: `killed/covered`, `killed/generated`, and
`failed/ran` (a false-alarm "rate" of 3.5). Obligation recall reached 2.0 separately, from
duplicate witness ids.

---

## Fixed on this branch

Ordered by severity. Every row was verified before and after.

### SEV-1 — a number or a check that was wrong, not merely missing

| # | Finding | Evidence |
|---|---|---|
| 1 | Mutation score, false-alarm rate and obligation recall all unbounded | 2.0 from a real run; 3.5 and 2.0 from reachable payloads |
| 2 | `corpora/**` in **no** `paths:` filter and **no** protected pattern | a corpus-only PR ran zero workflows while all seven required-check stubs reported green — and `config/testgen_eval.yaml:31` reads that corpus as its live dataset |
| 3 | `secret scan (gitleaks)` could pass **vacuously** | `paths:` is per-workflow; a docs/demo/corpora-only PR skipped `quality-gates.yml`, and the companion stub then reported the context green — a passing secret scan no scanner produced |
| 4 | 32 of 60 corpus items could not calibrate | the known-BAD `weak` suite was built from `live[0]` — the **most** discriminating assertion available — so it came out byte-identical to the known-GOOD `thorough` suite apart from the test function's name |

### SEV-2 — a guard that could not fail, or a gap nothing would report

| # | Finding | Evidence |
|---|---|---|
| 5 | `test_execution_opens_no_socket` was vacuous | monkeypatched the parent, asserted about a subprocess; would have passed with a hundred connections. Its docstring claimed the offline property was "asserted directly" |
| 6 | `is_shallow_clone`'s `True` branch had no test | replacing the body with `return False` passed the **entire suite**, verified. Had the git command changed, strict mode on a shallow CI clone would report all 53 refs as rot |
| 7 | `test_each_run_gets_its_own_working_directory` passed with `workdir = root` | the exact regression it was named for, at a cost of 4 subprocesses |
| 8 | F-058 asserted `test ⊆ disk`, never `disk ⊆ test` | F_062–F_065 were on disk, in the ledger and in CI, absent from the test module and the `--cov=` list |
| 9 | Wrongly-typed **nested** evidence raised out of the scorer | `AttributeError` aborts the whole run under ADR 0038 — the opposite of the package's stated contract |
| 10 | A mutant whose subprocess never ran was dropped silently | it stayed in the denominator, so a broken runner arrived as a low mutation score |
| 11 | Every failing test's exception was discarded | `green_on_correct: 3/4 failed` had no artifact anywhere saying why |
| 12 | The corpus's four calibration suites were **never executed** by any test | every check compared text: set membership, `startswith`, `count("assert ")` |

### SEV-3 — drift and rot

| # | Finding | Evidence |
|---|---|---|
| 13 | One `upload-artifact` SHA documented as `# v4` and `# v7.0.1` | a single dependabot commit preserved each file's comment format; `docs.yml` claimed a two-major-old action while running a current one |
| 14 | Dependabot never scanned `.github/actions/run-quality-gate` | `directory: "/"` scans `.github/workflows/` only; the composite action every workflow delegates to sat on `setup-python@v5` against v7.0.0 everywhere else |
| 15 | `experiments/backend-validation` unwatched | no CI job, no `coverage-floors.yaml` unit, no dependabot entry — and two 95% floors declared in its own `pyproject.toml` |
| 16 | `calibrated-merge-gate.yml` omitted `e2e-matrix` | beside a comment claiming it installs "the same extras quality-gates installs"; both `importorskip("openpyxl")` tests were silently skipped |
| 17 | `_case_lines` emitted `with pytest_raises():` | undefined in both the generated suite and the pytest-free runner. Unreachable today; a reachable version would have turned a "thorough" fixture into the "broken" one |
| 18 | Git subprocesses unbounded and un-isolated | no `timeout`; `GIT_DIR`/`GIT_CONFIG_*`/`core.hooksPath` from the host made a "throwaway" fixture neither throwaway nor a fixture |
| 19 | `"!"` raise-marker tested with `.startswith` at three sites | a reference value legitimately beginning with `"!"` would be misread as an exception at all three |
| 20 | Two ratio scorers hard-coded `passed = value > 0.0` | killing 1 of 100 mutants reported `passed=True` while the gate rule failed the same run |

### Raised in review of this PR, after the audit above was written

Recorded here rather than folded into the tables, so that what this audit found on its own
stays distinguishable from what a reviewer had to find for it.

| # | Finding | Evidence |
|---|---|---|
| 21 | `timeout_seconds` accepted anything `float()` accepted | `"abc"` raised `ValueError` **out of the target**, which aborts the whole run under ADR 0038 — one malformed item costs every other item's measurement. `-1` fired `TimeoutExpired` in under a millisecond, recording a fabricated timeout over a suite nothing had run; `nan`/`inf` disabled the limit the subprocess exists to enforce |
| 22 | A mutant id was interpolated into a filesystem path unsanitised | an id of `../../../../ESCAPED` wrote `focal.py` **outside the execution root**, verified. The index now in the label also closes a collision: two mutants sharing an id shared a sandbox |
| 23 | `timeout_seconds: true` became a 1-second limit | `bool` subclasses `int` and `float(True) == 1.0`, so the numeric guard could not see it. Every suite over that budget then reported a timeout it never earned |
| 24 | `_covered` guarded `i < len(grid)` but not `0 <= i` | a negative index counts from the END of the grid, so `differs_at: [-1]` made the last grid point stand in for a mutant that differs nowhere near it — coverage the suite never earned |
| — | `_suite_runner` ordering: docstring vs code | **Not taken as proposed.** The review asked for definition order to match the prose; the prose was the defect. Definition order is a property of a file a *model* wrote, so a regenerated suite with rearranged functions would execute differently — and `repetitions > 1` measures the target's variance, not variance acquired from the input |

**Finding 24 is a miss by this audit, not by the review.** It was in the raw output of this
audit's own test-practice pass (as "2.14 — negative `differs_at` index") and was dropped
when the twenty findings above were consolidated. Everything else in that pass was either
fixed or carried into "Open, not fixed here"; this one was neither, and nothing recorded
the decision because there was not one. A per-finding disposition column — fixed, deferred
with a reason, or rejected with a reason — would have made the omission visible at the time
it happened. That is the process gap; the code defect is fixed.

### New guards, each negative-controlled

- `tests/test_action_pins.py` — one SHA never carries two version comments; one resolved
  version never names two SHAs; no `uses:` is a floating tag; every composite action
  directory and python package root appears in dependabot.
- `tests/test_claude_hooks.py` — hook files and settings compared in both directions;
  behaviour asserted by running each hook, including against a malformed event.
- `scripts/validations/F_058.py` — `disk ⊆ test ∪ waived`, plus the waiver list checked for
  stale and phantom entries so it cannot quietly widen.
- `tests/test_protected_paths.py` — every dataset the shipped configs read is protected,
  derived from the configs rather than restated as a glob.
- `scripts/validations/F_048.py` — the secret scan runs on **every** pull request.
- `corpora/testgen/v1/manifest.json` — `weak_strictly_weaker_items: 60/60`, so the
  calibration claim is measured rather than asserted in prose.

---

## Two agent claims that did not survive verification

Recorded because an audit that only reports confirmed findings gives no sense of its own
error rate.

- **"F_062–F_065 are measured by no coverage gate"** was reported SEV-1 on the reading that
  they do not run. They **do** run: all four are `tier: fast` in `features.yaml` and
  `validate.py --tier fast` executes every one in CI, so a failure blocks. What was missing
  is coverage *measurement*. Real, and fixed — but SEV-2, not SEV-1.
- **"`corpora/**` is not in `PROTECTED_PATTERNS`"** named the wrong file
  (`check_protected_changes.py` rather than `eval_protected_paths.py`). The finding was
  correct; the location was not.

---

## Open, not fixed here

Each is real and each was judged out of scope for a branch already carrying three
workstreams. Ordered by what they cost if left.

### Correctness and safety

1. **The sandbox is not contained.** `_suite_runner` runs model-authored code with the
   parent environment, no `cwd` jail beyond convention, and no resource limits. A generated
   suite can read `os.environ` (API keys), write anywhere on disk, open sockets, and spawn
   grandchildren that survive the parent's `TimeoutExpired` — `subprocess.run` kills only
   the direct child. It can also **forge its own evidence**: `import focal;
   focal.__calls__.append(...)` fabricates coverage, and reading `focal.py` lets a suite tell
   reference from mutant. Given that "covered is measured rather than assumed" is ADR 0043's
   stated reason for the instrumentation, reward-hacking deserves a negative test.
   The new `test_a_suites_network_use_never_reaches_the_harness_process` pins that execution
   is out-of-process; it deliberately does **not** claim the sandbox is isolated.
2. **No aggregate wall-clock budget.** `DEFAULT_TIMEOUT_SECONDS = 30` is per subprocess.
   Measured worst case on the committed corpus: 7 runs × 30 s = 210 s per item; at
   `repetitions: 5` over 60 items that is ~17.5 h. A single pathological item is bounded; a
   systematically slow run is not. Wants `total_timeout_seconds` plus a
   `budget_exhausted` evidence flag.
3. **`implemented_in` accepts any commit-ish.** `features.schema.json:24` types it as a bare
   string and `ref_problem` accepts a branch name, a tag, or literally `HEAD` — which
   resolves and is trivially an ancestor of `HEAD`, so it passes forever. For a guard whose
   stated purpose is that provenance cannot be asserted but only demonstrated, a mutable ref
   is the exact hole.
4. **Corpus byte-identity is a cross-version assertion.** Every mutant goes through
   `ast.unparse`, whose formatting has changed between CPython releases, and
   `eval-harness-ci.yml` runs the root suite on 3.11, 3.12 **and** 3.13. The manifest records
   the seed and the grid but not the interpreter, and the failure message says "regenerate
   with `--write`" — misleading if the real cause is a version difference.

### Structure

5. **`tests/test_matrix_eval_tools.py` is 3,304 lines** (+743 on this branch). Exempt from
   the 500-line gate because it excludes `tests/`, so this is judgement rather than a
   violation. The seam is already drawn: lift `PIPELINES`, both tmp-path tables, the fixture
   writers, `_apply_tmp_path_params` and `_iter_components` into `tests/_m8_pipelines.py`
   beside `_m8_probe.py` — about 500 lines moved, and it makes `TestTmpPathParams` a test of
   an importable unit rather than of a same-file private. `tests/test_matrix_testgen_scorers.py`
   already set the precedent.
6. **`scripts/_testgen_corpus_lib.py` is at 463 of 500** after this branch. Its split is
   pre-drawn by its own section comments: mutation (templates, `_MutationOperator`,
   `_behaviour`, `_build_mutants`, `_build_obligations`) and suites (`GRID`, `SUITE_KINDS`,
   `_case_lines`, `_covering_indices`, `_build_suites`), the latter depending inbound only on
   `GRID` and `_Mutant`.
7. **The `add` focal fixture exists in four byte-identical copies** —
   `scripts/validations/F_065.py`, `tests/test_testgen_target.py`,
   `tests/test_matrix_eval_tools.py`, plus the config example. The coincidence between
   `differs_at: [1]`, `grid[1] == [2, 1]` and `assert add(2, 1) == -1` is the fixture's whole
   point; change `< 2` to `< 3` in one copy and two other files silently test something they
   no longer describe. `F_064.py` already establishes the fix (`from tests import _gitrepo`);
   a `tests/_testgen_fixtures.py` would do the same here.
8. **`tests/_gitrepo.py` is the 11th git-runner helper.** Its closest prior,
   `agent-core/tests/gitrepo.py`, is near-identical — now named in the docstring with the
   reason it is not reused (separate sub-project, separate rootdir).

### Test practice

9. **No property-based tests anywhere on this branch**, in a repository already wired for
   them: `tests/conftest.py` registers hypothesis profiles, `tests/test_agent_confidence.py`
   uses `@given`, and `agent-core/tests/test_property.py` has literally
   `test_ece_and_mce_in_unit_interval`. The four new scorers compute exactly that kind of
   metric — and were not bounded to the unit interval. The bounds are now enforced by
   `bounded_ratio` and pinned by example-based tests; a `@given` over arbitrary non-negative
   counts is the stronger form and would have found finding #1 first.
10. **Two determinism cells cannot fail.** `test_m5_determinism_*` call a pure function five
    times and re-order dict keys, which Python dict lookup is order-independent about by
    construction. They are matrix-row obligations, not evidence. Low severity, named so the
    matrix's own numbers are read correctly.

### Tooling

11. **`ruff` omits the `S` (bandit) ruleset** — 41 findings — in a repository that now
    executes model-authored code and parses XML with stdlib ElementTree
    (`scripts/regression_gate.py:152`, `S314`). Enabling `S` with a triaged per-file ignore
    list is a change of its own; enabling it silently would be 41 suppressions nobody read.
12. **13 inline coverage floors in `skills/`** are absent from `coverage-floors.yaml`, so the
    pin gate that protects every other floor does not protect theirs.
13. **`_EXTRA_PROVIDES` is only ever checked against `eval-harness-ci.yml`.** The
    `autoevals` gap that CI caught during WS-2, and the `e2e-matrix` gap fixed here, are the
    same shape: nothing cross-checks the model of which extra provides which component
    against the install lines of the jobs that run the suite.

---

## Skills and agents worth building from what this branch did by hand

Each is an action performed repeatedly, manually, in one session.

1. **`negative-control` — the highest-value one.** This audit ran ~14 negative controls by
   hand: revert the fix, assert the test fails, restore. That loop found the two vacuous
   tests, proved the clamp guards fire, and caught one test of mine that asserted nothing
   (`test_a_keyword_call_is_credited_as_coverage` passed with the fix reverted, because a
   second fix masked it — so the test was rewritten). The repo's own rule is *a check that
   cannot fail is not a check*, and nothing enforces it. `scripts/validations/F_052.py`
   already mutation-tests one list; generalising it into
   `scripts/negative_control.py --file X --replace A=B --test-selector Y` would make the
   discipline repeatable rather than a habit.
2. **`claim-feature-id`.** Landing an F-ID means four coordinated edits — `features.yaml`,
   `scripts/validations/F_0NN.py`, `_VALIDATOR_MODULES`, the `--cov=` list — and F-058 now
   enforces all four. It caught missing entries twice in one session. A skill that performs
   the whole set from a template is the exact shape a skill is for.
3. **`add-matrix-cell`.** A new M8 pipeline needs a `PIPELINES` entry, possibly a tmp-path
   table row, a regenerated `docs/matrix-coverage.md`, and a waiver check in both directions.
   Twenty were added this branch, each by hand.
4. **`.claude/agents/` is empty.** The three review passes behind this document were ad-hoc
   prompts. As agent definitions — `ci-wiring-auditor`, `anti-pattern-auditor`,
   `test-practice-auditor` — they become repeatable, and their prompts become reviewable
   artifacts rather than scrollback.

## Hooks and loops

**Added here.** `post-edit-protected-path.py` (PostToolUse) and
`stop-generated-artifacts.py` (Stop), both advisory and fail-open, both wired into
`.claude/settings.json` and guarded by `tests/test_claude_hooks.py`. They address the two
failures this branch hit repeatedly: editing a protected path without noticing, and leaving
a generated artifact stale until CI said so.

**Still worth having.**

- **A `PostToolUse` formatter.** `ruff format` ran manually four times this session and each
  run modified files just edited. A hook running `ruff format` + `ruff check --fix` on the
  edited file removes that churn entirely.
- **A `PreToolUse` guard on `git push`** that runs `scripts/validate.py --tier fast`. F-058
  caught missing ledger entries **after** a push, twice.
- **`scripts/fix_loop.py` remains inert**, correctly: `FIX_ENABLED = False`, with a
  `ScopeGuard` that physically cannot write to a protected path. ADR 0004 carries the human
  checklist required to enable it. Nothing here recommends changing that — an automated
  fix-until-green loop over an eval harness has the highest Goodhart risk in the system, and
  this audit found four separate ways the harness's own numbers could be wrong. That is an
  argument for keeping it off, not a gap.

---

## Wiring status

| Surface | State |
|---|---|
| Protected paths | 36 patterns, all reachable from a workflow filter (`check_guard_reachability`) |
| Required-check stubs | one stub per real job, both directions asserted; the secret-scan stub deleted as unsafe |
| Validators | 64 on disk, 45 coverage-measured, 19 waived by name in `F_058._UNMEASURED_BY_DESIGN`; all 63 ledger entries execute in `--tier fast` |
| Dependabot | 9 entries; every composite action directory and python package root covered, asserted |
| Action pins | every `uses:` SHA-pinned, every version comment self-consistent, asserted |
| Hooks | 3 files, 3 registered, both directions asserted |
| Coverage floors | root 96%, scripts 85%, four packages 95%, claude-foundation 85% — all pinned in `coverage-floors.yaml` **except** the 13 inline floors in `skills/` and the 2 in `experiments/` |
| Gate | `./scripts/quality-gate.sh all` PASS — 2459 passed / 32 skipped; `eval_harness` 98.66% branch coverage against the 96 floor |

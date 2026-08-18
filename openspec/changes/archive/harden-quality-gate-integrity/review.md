# Review: harden-quality-gate-integrity

**Reviewed:** this package's landed diff (`7115641` + `28c3ee9`) against base `7cdba73`
(`git merge-base --is-ancestor 7cdba73 HEAD` confirms real ancestry — linear history, no
rebase caveat needed), in two passes — a mechanical fact-check of every falsifiable claim in
`proposal.md`/`design.md`/`tasks.md`/`features.yaml` against the actual tree and real command
runs (verdicts CONFIRMED / CORRECTED / REFUTED), and an adversarial pass that tries to defeat
the design and verifies every attack before keeping it. Refuted attacks are recorded, not
deleted. House precedent: `openspec/changes/add-panel-judge/review.md`. This is an independent
review — no implementer self-report was read; every claim below was re-derived from the tree,
from real command output, or from reading upstream library source (`coverage`, `pytest-cov`,
`pytest`) directly.

## Verdict

**APPROVE WITH FOLLOW-UPS.** The core claim — `COV_FAIL_UNDER`, `COVERAGE_SOURCE`, and
`PYTEST_ADDOPTS` can no longer weaken the coverage gate at runtime, in any of the 7 packages,
including the one hand-maintained extension point the generator cannot reach — is true, and I
verified it far past the point of trusting the diff: I ran the pre-fix generator against the
new positive-control tests and watched exactly the 3 evasion-specific tests fail (the 2
baseline-correctness tests correctly still passed), then restored the fix and watched all 5
pass; I sourced the real, committed root `do_extra()` directly and fed it
`PYTEST_ADDOPTS=--no-cov` both with and without its guard, proving the guard is not decorative;
I independently re-derived the two-anchor floor agreement across all 7 packages in Python
rather than trusting the cross-check test's green; and I ran `shellcheck`, `ruff`, `mypy`, and
the full real `./scripts/quality-gate.sh all` end-to-end on 5 of the 7 packages, reproducing
the implementer's reported pass counts and coverage percentages to the decimal point in 4 of 5
cases. I found no correctness defect and nothing that would break a package's real CI as a
*result of this change*. The follow-ups are: a real but properly-scoped-out and
lower-severity sibling gap in `TYPECHECK_PATHS` (Pass 2, attack a/c), the independently
re-confirmed `makegen/render.py` sibling bug (Pass 2, attack d), a minor CI-coverage-list
wiring inconsistency for the new `F_054.py` (Pass 2, attack f, self-discovered), and a
pre-existing, unrelated, currently-red CI gate this phase inherits but did not cause (Pass 2,
attack g, self-discovered) that should be fixed before the consolidated PR ships so a reviewer
doesn't mistake it for this phase's fault.

---

## Pass 1 — mechanical fact-check (2026-08-17)

### render.py: both `_coverage_command` branches, byte-level

Read in full (`skills/quality-gate/scripts/gategen/render.py`) against
`git diff 7cdba73 HEAD -- skills/quality-gate/scripts/gategen/render.py`. The diff is exactly
five functions touched: `_ignored_override_notice` (docstring only), new
`_pytest_addopts_guard` (:104-118), `_coverage_command` (:141-159), `_step_commands`
(:162-173), `_variables` (:204-216). `model.py` (the `GateFacts` dataclass, field order) has
**zero** diff — the Phase 0 compat contract ("`GateFacts` field order... preserved") holds by
construction, not just by claim.

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | `--cov-fail-under=` is a literal number in **both** branches of `_coverage_command`, zero `$COV_FAIL_UNDER` left in the function | **CONFIRMED** | render.py:158 — `--cov-fail-under={facts.cov_fail_under}`, an f-string over `GateFacts.cov_fail_under: int` (model.py:38), identical in both branches (the `if/else` only selects `cov`, never touches the trailing `--cov-fail-under=` clause). Grepped the function body for `$COV_FAIL_UNDER`: zero hits outside the docstring's prose example. |
| 2 | `--cov=` is a literal in both branches | **CONFIRMED** | render.py:150-153 — single-source: `f"--cov={_quoted(facts.coverage_source)}"`; multi-source: per-source `_quoted((src,))`. Neither references `$COVERAGE_SOURCE`. |
| 3 | `_variables()` no longer emits either variable | **CONFIRMED** | render.py:213-216 — only `PYTHON` and (conditionally) `TYPECHECK_PATHS` remain. Diff shows the two `COVERAGE_SOURCE`/`COV_FAIL_UNDER` `out.append(...)` lines deleted outright, not merely edited. |
| 4 | `PYTEST_ADDOPTS` guard wired into **both** `do_test` and `do_coverage` | **CONFIRMED** | render.py:170 (`steps["test"] = [*_pytest_addopts_guard(), ...]`) and :157 (`*_pytest_addopts_guard()` inside `_coverage_command`'s return). Unit-verified: `test_do_test_guards_against_pytest_addopts`/`test_do_coverage_guards_against_pytest_addopts` in `test_render.py` additionally assert **ordering** (`unset` indexes before the pytest invocation), not just presence. |

### The 7 regenerated `quality-gate.sh` copies — read directly, not trusted via `--check`

Read **all 7** files in full (not just the 2 the task required), plus their full `git diff`:
root, `agent-core/`, `behavioral-regression/`, `claude-foundation/`,
`experiments/backend-validation/`, `flow-corpus/`, `flow-protocol/`.

- Every `do_coverage()` carries, in order: the `COVERAGE_SOURCE` notice, the `COV_FAIL_UNDER`
  notice, the `PYTEST_ADDOPTS` notice + `unset`, then a pytest-cov line with a literal
  `--cov=` and literal `--cov-fail-under=N` — **CONFIRMED** for all 7, by eye.
- Every `do_test()` carries the `PYTEST_ADDOPTS` notice + `unset` before `"$PYTHON" -m
  pytest` — **CONFIRMED** for all 7.
- Root's hand-maintained `do_extra()` (`scripts/quality-gate.sh:70-79`) carries the identical
  guard idiom ahead of its direct `"$PYTHON" -m pytest tests --cov=scripts
  --cov-config=scripts/.coveragerc ...` line — **CONFIRMED**, and proven non-decorative below
  (Pass 2, attack b).
- `claude-foundation`'s `do_extra()` (foundation_tools.validate/scan) and
  `experiments/backend-validation`'s `do_extra()` (`backend_validation.cli preflight`) invoke
  no pytest at all — correctly **not** hand-edited, and I confirmed by reading every one of
  the other 5 packages' post-marker regions that **none** of them defines a `do_extra()` that
  invokes pytest (`agent-core`, `behavioral-regression`, `flow-corpus`, `flow-protocol` have no
  `do_extra()` at all). Root is genuinely the only hand-maintained pytest call site in scope,
  and it is the only one hand-edited.
- The frozen fixture `skills/project-setup/evals/fixtures/with-gate/scripts/quality-gate.sh`
  has **zero** diff against `7cdba73` — **CONFIRMED** untouched.
- I did **not** stop at `gen_gate.py --check` passing (ran it for all 7 anyway — all "up to
  date"). I additionally read `gen_gate.py::_check` itself: it does a byte-exact string
  compare of the generator-owned prefix (`existing_prefix != fresh_prefix`), which combined
  with reading every diff by eye rules out both "the content is wrong but `--check` doesn't
  notice" and "unrelated content silently drifted."
- `shellcheck 0.9.0` (installed fresh into this sandbox for the purpose) reports **zero**
  warnings on all 7 files — the "ShellCheck-clean" design goal in render.py's own module
  docstring holds for the new lines, not just the old ones.

### Positive-control tests: run for real, and proven non-vacuous

Ran `cd skills/quality-gate && python -m pytest tests/test_coverage_gate_integrity.py -v` —
**5 passed** (`test_low_coverage_fixture_fails_the_real_gate`,
`test_high_coverage_fixture_passes_the_real_gate`,
`test_cov_fail_under_zero_does_not_evade_the_low_coverage_gate`,
`test_pytest_addopts_does_not_evade_the_low_coverage_gate`,
`test_coverage_source_override_does_not_change_what_is_measured` — 5, not 4; the file adds a
`COVERAGE_SOURCE` case beyond the plan's named minimum).

**Non-vacuousness, proven not assumed.** Copied out the current `render.py`, replaced it with
`git show 7cdba73:skills/quality-gate/scripts/gategen/render.py` (a real, reachable pre-fix
baseline — this phase's own base commit), and re-ran the same 5 tests:

```
FAILED test_cov_fail_under_zero_does_not_evade_the_low_coverage_gate
FAILED test_pytest_addopts_does_not_evade_the_low_coverage_gate
FAILED test_coverage_source_override_does_not_change_what_is_measured
3 failed, 2 passed in 3.81s
```

Exactly the 3 evasion-specific tests fail against the pre-fix generator (`COV_FAIL_UNDER=0`
genuinely produced `returncode=0` pre-fix; `PYTEST_ADDOPTS=--no-cov` genuinely produced
`WARNING: Coverage disabled via --no-cov switch!` + `returncode=0` pre-fix), while the 2
baseline-correctness tests (no injected override) correctly pass in **both** versions — this
is exactly the shape a non-vacuous regression suite should have. Restored the fixed
`render.py` afterward; `git status` confirmed the worktree was clean throughout and after.
**CONFIRMED**, with unusually strong evidence.

### `python scripts/validate.py --tier fast`

Ran for real: **`OK: 52 done; ran 52 for tier(s) ['fast']`**, including `F-054 passed`. Ran
`python scripts/validations/F_054.py` standalone too — every one of its per-file assertions
(7 scripts × 5 checks + 4 pyproject.toml checks = 39 checks) printed `OK`. **CONFIRMED.**

### The 4 `pyproject.toml` regex fixes — literal characters, not description

Read the raw diff hunks and parsed each file with Python's `tomllib` (not just grepped) to
confirm the *decoded* regex, not just the source bytes:

```
agent-core/pyproject.toml           -> exclude_also contains '^\s*\.\.\.$'
behavioral-regression/pyproject.toml -> exclude_also contains '^\s*\.\.\.$'
flow-protocol/pyproject.toml        -> exclude_also contains '^\s*\.\.\.$'
flow-corpus/pyproject.toml          -> exclude_also contains '^\s*\.\.\.$'
```

Matches root `pyproject.toml:185` and `scripts/.coveragerc`'s `exclude_lines` exactly.
Independently swept the **whole repo** (`find . -iname pyproject.toml`, `-iname .coveragerc`)
for any other ellipsis-exclude pattern that might have been missed: `experiments/backend-
validation/pyproject.toml` has no ellipsis exclude at all (correctly not in the 4-file list);
none of the 5 `skills/*/evals/fixtures/**/pyproject.toml` fixtures declare one either. The
4-file scope is complete, not under- or over-claimed. **CONFIRMED.**

Independently re-verified the semantics the fix (and design.md's regex-safety argument) rests
on, by reading the installed `coverage==7.15.4` source directly rather than trusting the
design doc's Context-7-unavailable fallback:
`coverage/parser.py:142-162` (`lines_matching`) uses `re.finditer(regex, self.text,
flags=re.MULTILINE)` and its own docstring says "The entire line needn't match, just a part of
it" — confirms `exclude_also`/`exclude_lines` really is a partial-line search, not a full-line
match, exactly as the anchoring fix assumes. `coverage/config.py:559`
(`self.exclude_list += self.exclude_also`) confirms `exclude_also` really is additive-only.
Both semantics **CONFIRMED** against real library source, closing the one gap design.md itself
flagged as unverified-via-MCP-this-session.

### ADR 0009 errata

`docs/decisions/0009-tech-debt-audit-and-compat-surface.md:84` (§4, pre-existing text) really
does say "the root `exclude_lines` was aligned with the sub-packages'" — the errata targets a
real claim, not a strawman. New errata block (`:5-17`) is placed as a bullet inside 0009's own
`- Status: / - Date:` bullet-list header, which is 0009's own convention (0032's precedent
uses a plain paragraph after `**Date**:` since 0032's header isn't a bullet list — the
implementer adapted the *pattern*, not copy-pasted the *markup*, which is the right call).
**CONFIRMED.**

### `tests/_e2e_matrix.py::_floor_from_gate_script` + the two-anchor cross-check

The regex changed from `COV_FAIL_UNDER="\$\{COV_FAIL_UNDER:-(?P<n>\d+)\}"` to
`--cov-fail-under=(?P<n>\d+)` (`tests/_e2e_matrix.py:723-731`). Ran
`test_floor_anchors_agree_with_each_other` — passes. Per the task's explicit instruction not
to trust the test's green alone, independently re-derived `em.derive_packages(ROOT,
em.derive_workflows(ROOT))` in a raw Python shell against the real, regenerated tree:

```
agent-core   -> ('pyproject.toml=95', 'quality-gate.sh=95')
behavioral-regression -> ('pyproject.toml=95', 'quality-gate.sh=95')
claude-foundation -> ('pyproject.toml=85', 'quality-gate.sh=85')
experiments/backend-validation -> ('pyproject.toml=95', 'quality-gate.sh=95')
flow-corpus  -> ('pyproject.toml=95', 'quality-gate.sh=95')
flow-protocol -> ('pyproject.toml=95', 'quality-gate.sh=95')
root         -> ('pyproject.toml=96', 'quality-gate.sh=96')
```

Every package genuinely carries **two** independent, agreeing anchors — the claim that this
was "re-verified directly... rather than trusted from the test suite staying green" is itself
true, and I have now independently reproduced that same re-verification myself. **CONFIRMED.**

### Docs, evals, marketplace version

- `SKILL.md` §2/§3 text changes read accurately (no longer claims single-source
  `COVERAGE_SOURCE`/`COV_FAIL_UNDER` are overridable). **CONFIRMED.**
- `evals.json`'s 3 new/changed assertions (`--cov-fail-under=85`, the two notice strings) were
  not just read — I deleted `.skill-validation/`, ran the eval's own literal command
  (`python scripts/gen_gate.py --root evals/fixtures/full --out
  .skill-validation/quality-gate.sh`), and grepped the real output: all present, `fail_under =
  85` in the fixture's own `pyproject.toml:22` matches the asserted literal exactly.
  **CONFIRMED.**
- `skills/marketplace.yaml` `1.1.0` → `1.2.0` matches `SKILL.md` frontmatter; `python
  scripts/skill_marketplace.py validate` passes for real. **CONFIRMED.**

### End-to-end runs against the real repo (beyond what the task required, done for the
highest-stakes phase)

Reproduced `tasks.md`'s reported Verification numbers directly, via the real regenerated
scripts, not the generator's own unit tests:

| Package | Command run | tasks.md claim | What I measured |
|---|---|---|---|
| root | `./scripts/quality-gate.sh coverage` then `do_extra` body directly | 96.98%/96 (1625 passed, 41 skipped); scripts-coverage 93.35%/85 | **Exact match both**: 96.98%/96, 1625 passed/41 skipped; 93.35%/85 |
| agent-core | `./scripts/quality-gate.sh all` | 98.49%/95 (788 passed, 2 xfailed), PASS | **Exact match**: 98.49%/95, 788 passed/2 xfailed, PASS |
| behavioral-regression | `./scripts/quality-gate.sh all` | 100%/95 (157 passed), PASS | **Exact match**: 100%/95, 157 passed, PASS |
| flow-corpus | `./scripts/quality-gate.sh all` | 100%/95 (163 passed), PASS | **Exact match**: 100%/95, 163 passed, PASS |
| flow-protocol | `./scripts/quality-gate.sh all` | 100%/95 (21 passed), PASS | **Exact match**: 100%/95, 21 passed, PASS |
| claude-foundation | lint/typecheck/coverage individually | 96.03%/85 (136 passed), all green | **Exact match**: 96.03%/85, 136 passed, all green |
| experiments/backend-validation | lint/coverage individually; typecheck | 97.72%/95 (355 passed); typecheck fails on missing `types-jsonschema` stubs (pre-existing env gap) | lint green; **355 passed matches**, but I measured **97.61%/95** (stable across 2 runs), not 97.72% — see Pass 1 correction below. typecheck failure **CONFIRMED** real and reproduced verbatim, `types-jsonschema>=4` genuinely declared in `pyproject.toml:41` and genuinely absent from this sandbox (`pip show` confirms not installed, no local index to install it from) |

Also independently ran the skill's own full CI job locally end-to-end (not just its test
suite): `ruff check`, `ruff format --check`, `mypy` (both clean), `pytest tests --cov=gategen
--cov=gen_gate --cov-fail-under=95` (99.30%, 78 tests), and `python scripts/validate_skill.py
--skill . --tier structural,behavioral` — `OK`.

### Corrections (Pass 1)

| # | Finding | Correction |
|---|---|---|
| C1 | **F-054's `implemented_in` SHA was initially wrong.** Commit `7115641` landed `features.yaml` with `implemented_in: 7cdba736...` (the *base* commit, since a commit can't self-reference its own SHA) | Already self-corrected in this same branch, commit `28c3ee9` ("chore(features): record F-054's real implemented_in SHA"), which I verified points at `711564123e463da1fd9d5f60c10488ea9cb1e7c7` — confirmed via `git rev-parse 7115641` to be the exact, correct full SHA. No open issue; noted because the task asked for exactly this kind of check. |
| C2 | **Positive-control tests landed in a new file, not the file the plan named.** Phase 1's table says new cases belong in `skills/quality-gate/tests/test_gen_gate.py`; they instead landed in a new `test_coverage_gate_integrity.py` | Not a defect — an improvement over the letter of the plan. `test_gen_gate.py`'s shared `_project()` fixture hardcodes `fail_under=0` for *other* tests' unrelated reasons; reusing it here would have either broken those tests or produced exactly the vacuous-threshold problem this phase exists to close. The new file also ships a 5th test (`COVERAGE_SOURCE` override) beyond the plan's 4 named cases. Intent fully met, letter not. |
| C3 | **`experiments/backend-validation` coverage figure does not reproduce exactly.** `tasks.md` reports 97.72%/95; I measured 97.61%/95, stable across 2 independent runs of the real `./scripts/quality-gate.sh coverage` | Both numbers clear the 95% floor by 2.6+ points; the 0.11-point gap is almost certainly environment/optional-dependency variance (this is exactly the kind of package where `if` import guards make coverage installation-sensitive — the `types-jsonschema` gap above is independent evidence this sandbox's dependency set differs from whatever produced the original figure). Does not touch the fix's correctness — the regex/env-var logic this phase changes is not what's being measured here at all. Recorded as a minor factual-precision note, not a defect. |

---

## Pass 2 — adversarial (2026-08-17, dated separately per house method)

Assume the design is wrong; try to prove it. Each attack was executed against the real tree,
not reasoned about in the abstract.

### (a) Is there ANY remaining env-var evasion of the coverage gate?

Grepped `render.py`'s own output for every `${...}` shell expansion it can emit: only
`PYTHON` (`:213`) and `TYPECHECK_PATHS` (`:215`, single-path only) remain live overrides.
Verified this holds in the **real generated files** too (not just the generator source): ran
`COV_FAIL_UNDER=0 COVERAGE_SOURCE=nonexistent PYTEST_ADDOPTS=--no-cov ./scripts/quality-
gate.sh coverage` against the **real root package** (not a synthetic fixture) — exit 0, real
96.98%/96 report unchanged, and all three "is ignored" notices printed to stderr. No 4th
lever exists in the coverage/test steps.

**Is `PYTHON` itself a comparable evasion?** Considered and **REFUTED as comparable**, kept
as a residual note. Controlling `$PYTHON` could fake *every* step (not just coverage) by
pointing it at a wrapper binary — a strictly more powerful attack. But it is a different
threat class: no CI workflow sets `PYTHON` (grepped `.github/**` — zero hits), so it is not
reachable by a PR the way an ambient shell env var is; and it is legitimately necessary
(venvs, pyenv, Windows `py.exe`) in a way a numeric coverage threshold never is — there is no
generation-time literal that could replace it across machines. Whoever controls `$PYTHON` on
the runner already controls the outcome of every check, gate design notwithstanding. Not a
gap this shell script's design could close.

**`TYPECHECK_PATHS` — do I agree it "cannot fool a numeric threshold"?** Agree with the
literal claim, **but constructed a real, working degradation the brief's framing doesn't
fully cover** (attack folded into (c) below since the task groups them — kept as one finding).

### (b) Is root's hand-edited `do_extra()` guard dead code?

**REFUTED, with direct proof, not just reasoning.**

1. Traced reachability: `eval-harness-ci.yml` → `run-quality-gate` action → `check: make
   check` → root `Makefile:36` → `./scripts/quality-gate.sh all` → `do_all()` (`scripts/
   quality-gate.sh:44-53`) → `if declare -F do_extra; then do_extra; fi`. Real CI genuinely
   calls this function on every push/PR touching root's trigger paths.
2. Confirmed the underlying pytest invocation is exploitable in principle:
   `pytest_cov/plugin.py:270-271` shows pytest-cov falls back to `cov_config.fail_under`
   (i.e. `scripts/.coveragerc`'s `fail_under = 85`) when no `--cov-fail-under` CLI flag is
   given — which `do_extra()`'s invocation deliberately omits, relying on the config file.
   Ran the exact same command **without** the guard, with `PYTEST_ADDOPTS=--no-cov` set:
   `WARNING: Coverage disabled via --no-cov switch!`, exit **0** — proves the pre-fix
   `do_extra()` (which had *no* guard at all, hand-maintained region, generator can't reach
   it) was silently exploitable exactly like the coverage step was.
3. Ran the **real, committed** `do_extra()` (sourced directly out of `scripts/quality-
   gate.sh`, not a hand-copy) with the same `PYTEST_ADDOPTS=--no-cov`: full coverage report
   still printed, `Total coverage: 93.35%`, `Required test coverage of 85.0% reached`, and
   stderr contained `quality-gate: PYTEST_ADDOPTS is ignored; this stage is a gate and has no
   opt-out`. The guard is real, wired into the real function, and neutralizes a real,
   independently-reproduced evasion.

### (c) Stress-testing `TYPECHECK_PATHS` as "not a numeric-threshold problem"

**Constructed a working attack; CONFIRMED it exists; CONFIRMED it is pre-existing and
correctly out of this phase's scope; recommend a follow-up, not a block.**

```
$ echo "x: int = 1" > /tmp/.../trivial_dir/trivial.py
$ TYPECHECK_PATHS=/tmp/.../trivial_dir python3 -m mypy "$TYPECHECK_PATHS"
Success: no issues found in 1 source file      # exit 0
```

Pointing `TYPECHECK_PATHS` at any trivially-clean directory makes `do_typecheck()` report
success while never touching the real package — the pass/fail *outcome* is still foolable,
even though there is no *percentage* to inflate. This means the brief's "cannot fool a numeric
threshold" framing is true narrowly but incomplete: gate integrity is about whether the
reported outcome reflects the real code, and this shows it can not, for typecheck, the same
way `COVERAGE_SOURCE` could for coverage before this fix. (Ruled out the cheaper version of
this attack: pointing at an empty/nonexistent directory — mypy exits 2, "There are no .py[i]
files", which `set -euo pipefail` correctly turns into a loud gate failure, not a silent
pass. The attack requires a pre-existing, syntactically-valid decoy target, not a bare env
var.)

Why this does **not** change the phase's verdict:
- **Pre-existing, not introduced.** `_typecheck_commands`, `_typecheck_env_form`, and the
  single-path declaration in `_variables()` have zero diff in this change — confirmed via
  `git diff 7cdba73 HEAD`. This attack works identically before and after `harden-quality-
  gate-integrity`.
- **Not reachable via real CI.** Grepped `.github/**` for `TYPECHECK_PATHS` — zero hits, same
  as `PYTHON`. No workflow sets it.
- **Meaningfully harder to trigger than the coverage findings.** `COV_FAIL_UNDER=0` requires
  no supporting files and could leak from a stale shell rc or a copy-pasted doc snippet by
  accident. This attack needs a pre-existing, syntactically-valid decoy directory the
  attacker controls — deliberate setup, not an ambient accident.
- **Explicitly scoped out, with reasoning, in `proposal.md`'s Scope/non-goals** and Phase 0's
  file-collision table, not silently dropped.

**Recommended follow-up** (not required for this merge): a later phase could close this the
same way `COVERAGE_SOURCE` was closed — promote the single-path `TYPECHECK_PATHS` form to a
generation-time literal too, retiring the "documented debug affordance" framing now that its
sibling variables no longer get that treatment. Worth a one-line callout in `design.md`'s
"What was found but is out of scope" section alongside the `makegen` finding, since it's the
same *kind* of finding (a debug affordance that turns out to double as a gate-integrity hole)
that section already documents one instance of.

### (d) Independently verifying the `makegen/render.py` sibling-bug claim

**CONFIRMED**, read cold, not cross-checked against the proposal's own description first.

`skills/project-setup/scripts/makegen/render.py:82`: `cmd = "$(PYTHON) -m pytest
--cov=$(COVERAGE_SOURCE) ... --cov-fail-under=$(COV_FAIL_UNDER)"`, and `:130-131`:
`COVERAGE_SOURCE ?= {facts.coverage_source}` / `COV_FAIL_UNDER ?= {facts.cov_fail_under}` —
GNU Make's `?=` is the Makefile analogue of bash `${VAR:-default}`: both an environment
variable and a `make coverage COV_FAIL_UNDER=0` command-line override win over it, with zero
warning either way. Genuinely the same evasion shape as the pre-fix `render.py`, in a
different templating language. `skills/project-setup/tests/test_render.py:68-69` and
`evals.json:12` currently **assert this override behavior as a correct, intended feature** —
this skill has not yet recognized it as a gap, which is exactly what `proposal.md` says.

This code path is gated by `not delegate` (`_coverage_target`/`_variables`, `render.py:78-82,
129-131`) — it only fires for a project whose Makefile does **not** delegate to a
`quality-gate.sh`. Swept every real Makefile in this repo (`root`, `agent-core`,
`behavioral-regression`, `experiments/backend-validation`, `flow-corpus`, `flow-protocol`,
`claude-foundation`) for `COVERAGE_SOURCE`/`COV_FAIL_UNDER` — **zero hits**: every package
here already delegates, so this pattern has **zero current blast radius in this repo**, only
in a hypothetical future Makefile-only (no quality-gate skill) project. `proposal.md`'s
characterization — "found... but out of scope... a named follow-on, not a silently dropped
gap" — is accurate, not overstated, and I'd add: the CLI-argument override vector
(`make coverage COV_FAIL_UNDER=0`) is arguably a slightly *broader* surface than the bash
case, since it needs no shell export at all — worth noting for whoever picks up the follow-on.

### (e) Did regenerating 7 scripts change anything unrelated to this fix?

**REFUTED** — read all 7 full diffs (not just the targeted hunks): every diff touches only
`do_test()`, `do_coverage()`, and the two deleted `_variables()` lines. `do_lint()` and
`do_typecheck()` are byte-identical in every file (no diff shown for those functions
anywhere). Header/provenance comment lines (`# regenerate: ...`) are unchanged in all 7 —
no generator-version-bump artifact. File permissions unchanged (`git diff --summary` shows no
mode changes; all 7 remain `rwxr-xr-x`). `gen_gate.py --check`'s comparison is a byte-exact
prefix string equality (`existing_prefix != fresh_prefix`, `gen_gate.py:50`), not a fuzzy
check, and all 7 report "up to date." Combined with `shellcheck`/`ruff`/`mypy` all clean
across the touched packages, I'm confident nothing incidental slipped in.

### (f) Self-discovered: `F_054.py` isn't wired into the "Quality-gate tooling coverage" CI step

Its 3 closest precedents by convention — `F_031` (explicitly named as this file's style
match), `F_050`, `F_052`, `F_053` — are all imported in `tests/test_validation_scripts.py`
and listed in `quality-gates.yml`'s dedicated `--cov=F_0NN ...` enumeration for the
"Quality-gate tooling coverage (>=85%)" step. `F_054` is in **neither** list. Verified this is
not a phantom concern by running the exact CI command locally end-to-end: 422 passed,
93.56%, no warning about `F_054` — because it's absent from *both* sides of the drift-guard
(`test_imported_validators_and_the_ci_cov_list_agree`), there's nothing to disagree about, so
this specific gap is invisible to that guard by construction. **Not a CI break** — confirmed
empirically — and `F_054.py` is still genuinely exercised (for real, against the real 7
scripts and 4 pyproject.tomls) via `scripts/validate.py --tier fast`, which I also ran. This
is a minor consistency nit: a large minority of `F_0NN.py` scripts are *not* in this curated
list either, so it's not clearly a mandatory step for every new number — but given `F_054`
explicitly claims to match `F_031`'s style, matching its CI treatment too would be the more
consistent choice. **Recommended follow-up, not a blocker.**

### (g) Self-discovered: a pre-existing, unrelated, currently-red hard CI gate this phase inherits

`python scripts/check_size_budget.py` (the "Source-file size budget (hard gate)" step in
`quality-gates.yml`) fails today: `experiments/backend-validation/backend_validation/
airgap_phase.py` (883 lines) and `.../clients/opik.py` (604 lines) both exceed the 500-line
cap. Verified this is **not caused by this phase**: neither file appears in this diff at all
(`git diff 7cdba73 HEAD --stat` — no hits), and both were already exactly 883/604 lines at the
base commit `7cdba73` (`git show 7cdba73:<path> | wc -l`). Traced further: `main` is at
`184d161`, and `159460a` (this worktree's own base) is *not yet merged into* `main` — the
oversized files don't exist on `main` at all yet. This is inherited baseline breakage from the
still-unmerged backend-validation/Opik work, not something `harden-quality-gate-integrity`
touches, worsens, or could plausibly be asked to fix within its own scope (root/4-pyproject/
generator only).

**Not counted against this phase's verdict** — it isn't this phase's defect, and I confirmed
by running the check that Phase 1's own changes have zero relationship to it. **Flagged,
not blocked**, because the task's own framing ("if you find anything that could actually break
a package's real CI") deserves a straight answer: yes, a real, currently-red, hard CI gate
exists in the tree this phase's branch is built on, and whoever assembles the final
consolidated PR (per the plan's "Reconvergence" section) should fix or explicitly waive it
first — otherwise a green Phase 1 diff will still show red CI for reasons a reviewer could
easily misattribute to this change.

---

## Residual risk

- **`TYPECHECK_PATHS` and `PYTHON` remain live env overrides.** Both deliberately out of
  scope; `PYTHON` is orthogonal (a different threat class, not closable at this layer);
  `TYPECHECK_PATHS` is a real but low-severity, high-attacker-effort, CI-unreachable gap
  worth a follow-up phase (Pass 2, attack c).
- **`makegen/render.py` ships the identical evasion pattern today**, currently inert in this
  repo (no Makefile here uses the vulnerable code path) but live for the next Makefile-only
  consumer of `project-setup`. Confirmed real, confirmed inert-for-now, tracked as a named
  follow-on rather than silently dropped (Pass 2, attack d).
- **The blanket `unset PYTEST_ADDOPTS` has no allowlist** — a legitimate future use of
  `PYTEST_ADDOPTS` (e.g. `-n auto` for xdist parallelism) would also be silently cleared.
  Verified no current workflow or config in this repo relies on it (`grep -r PYTEST_ADDOPTS
  .github/` — zero hits), so this is a deliberate, currently-costless trade-off ("a gate stage
  has no opt-out," per `design.md`), not an active problem.
- **Pre-existing size-budget CI redness in `experiments/backend-validation/`** (Pass 2, attack
  g) will surface on the consolidated PR regardless of this phase's own correctness, and
  should be resolved or explicitly waived before that PR is judged by its CI status.

## Overall verdict

**APPROVE WITH FOLLOW-UPS.**

The security-relevant claims — literal `--cov-fail-under=`/`--cov=` in both branches, the
`PYTEST_ADDOPTS` guard on every real pytest invocation including the hand-maintained one, the
anchored exclude regex, the two-anchor cross-check staying real — are all CONFIRMED by direct
execution against the real tree, not by trusting the diff or the implementer's own report.
Nothing found rises to a BLOCK: every attack that landed a real hit (TYPECHECK_PATHS,
makegen/render.py) is pre-existing, explicitly out of scope, and not reachable through this
repo's real CI; every attack aimed at *this* phase's own new code (dead-code do_extra guard,
vacuous positive controls, unintended regeneration side effects, coverage-config semantics)
was refuted with direct evidence.

**Follow-ups for a later phase (none blocking this merge):**
1. Promote `TYPECHECK_PATHS`'s single-path form to a generation-time literal, closing the
   pass/fail-outcome bypass demonstrated in Pass 2 attack (c) — same shape as this phase's own
   fix, applied to the one remaining sibling.
2. Fix `skills/project-setup/scripts/makegen/render.py`'s analogous `COVERAGE_SOURCE ?=`/
   `COV_FAIL_UNDER ?=` pattern (already tracked in this phase's own `design.md`/`features.yaml`
   notes; independently reconfirmed real in Pass 2 attack (d)).
3. Add `F_054` to `tests/test_validation_scripts.py`'s imported set and `quality-gates.yml`'s
   `--cov=` enumeration, matching the treatment its stated style-precedent `F_031` gets (Pass
   2 attack f).
4. Resolve or explicitly waive the pre-existing `check_size_budget.py` failure in
   `experiments/backend-validation/` before the consolidated PR is opened, so it doesn't read
   as a Phase 1 regression (Pass 2 attack g).

---

## Follow-up review -- 2026-08-18

**`spec-guardian` + `peer-reviewer`, dispatched for real.**

**Method note.** Everything above was produced by a `general-purpose` subagent inlining the
two-pass method — the case `add-foundation-reviewer-charters/tasks.md` §4 records as the one
this repo's own sessions actually hit (`claude-foundation` staged, not plugin-loaded, ADR
0028). This section is different: it was produced by the actual named
`foundation:spec-guardian` and `foundation:peer-reviewer` subagent types, dispatched from a
real `claude -p --plugin-dir claude-foundation` session — the functional proof
`add-foundation-reviewer-charters`'s task 4 asked for and had left genuinely blocked. Both
charters, in character, correctly flagged their own tool limitation (`Read`/`Grep`/`Glob`
only, no `git`/Bash) rather than fabricating confidence, and reviewed against the *current*
working tree — this package has since been archived (`changes/archive/`), so some of what
follows is drift between the original merge and today, not a defect this phase introduced.
Findings are lightly reformatted for this artifact; nothing substantive was cut.

### spec-guardian verdict

**Verdict: conforms** (with material caveats on verification method and one stale follow-up).

- **Follow-up #3, above, is resolved and should be struck.** `tests/test_validation_scripts.py:43`
  now imports `F_054`, and `.github/workflows/quality-gates.yml:178` includes `--cov=F_054` —
  confirmed by direct read. (Whether this landed inside the original diff range or arrived via
  the later `pin-lockstep-tool-versions` change is not determinable without `git`; either way,
  the follow-up is closed.)
- **The `eval-change-approved` label / CODEOWNERS review is a GitHub PR-metadata claim** that
  no repository file can confirm or deny — flagged as unverifiable-from-repo evidence per
  charter Rule 3, not assumed. The protected-path hits it should cover: `features.yaml`,
  `tests/_e2e_matrix.py` (root `tests/**`), `scripts/validations/F_054.py`.
- **`skills/quality-gate/tests/**` is not actually in `scripts/eval_protected_paths.py`'s
  `PROTECTED_PATTERNS`**, despite `tasks.md` tagging its positive-control tests `[P]`.
  `proposal.md` is self-aware about this (voluntary discipline, not CI-guarded) — not drift,
  but worth stating explicitly.
- **Every core technical claim spot-checked against the current tree holds**: the generator's
  literal `--cov-fail-under=`/`--cov=`, the unconditional ignored-override notices, the
  `PYTEST_ADDOPTS` guard wired into both the generated and hand-maintained paths, the anchored
  regex (2 of 4 packages independently re-checked), `F-054`'s `features.yaml` row, the ADR 0009
  errata, the skill version bump, and all 5 named positive-control tests.
- **Declared non-goals verified still true**: `makegen/render.py`'s analogous bug remains
  untouched (correctly out of scope here), and — independently reconfirmed —
  `experiments/backend-validation/{airgap_phase.py,clients/opik.py}` (884/605 lines) still
  exceed the size budget, matching this review's own Pass 2 attack (g) as still open.

### peer-reviewer verdict

**Verdict: approve the code; reject four documentation claims and one prior refutation as
written.** Nothing found is a correctness defect in the shipped shell scripts. One live,
unclosed env lever of exactly the class this change exists to close was found by the
adversarial pass.

**Pass 1 — mechanical fact-check.** 23 claims CONFIRMED outright (generation-time literals in
both call sites, the notice/guard wiring, all 7 scripts, the anchored regex in all 4 named
packages, `_floor_from_gate_script`'s updated regex, the ADR errata, version bumps, eval
assertions, both declared non-goals, the "no prior positive control existed" claim). Eight
corrected or refuted:

- **`proposal.md`'s "every one of the 7 packages uses single-source coverage" — REFUTED.**
  `claude-foundation` is multi-source (`source = ["foundation_tools", "hooks"]`,
  `claude-foundation/pyproject.toml:71`); the real figure is 6 of 7. The prior review did not
  catch this.
- **`design.md`'s "two-branch parity" section and its `_coverage_env_form()` citation —
  CORRECTED/REFUTED.** No such branch or function exists at HEAD; `render.py:151` is a single
  unconditional comprehension (behaviour-preserving collapse, verified). `design.md` describes
  code that no longer exists — landed after the original review was written, or after this
  phase, undeterminable without `git`.
- **`spec.md`'s "cannot be weakened by anything set in the calling environment" — REFUTED as an
  unqualified capability statement.** `PYTHON="${PYTHON:-python3}"` is a live, total override
  in all 7 scripts, and see the `COVERAGE_RCFILE` finding below. The individual scoped
  Requirements below that sentence are fine; only the umbrella claim over-reaches.
- **`SKILL.md`'s "a stderr notice either way" — CORRECTED.** False for the `test` step, which
  emits only the `PYTEST_ADDOPTS` notice. The substantive "no effect" claim holds.
- **`spec.md`'s "every gate step that invokes pytest SHALL clear PYTEST_ADDOPTS" — CORRECTED
  (scope).** True for the 7 generated scripts + root's `do_extra()`; not true for ~15 CI steps
  across `skills-ci.yml`/`quality-gates.yml`/`claude-foundation-ci.yml` that invoke pytest
  directly. Low practical risk (GitHub-controlled env), but unacknowledged in any of
  `proposal.md`/`design.md`/`review.md`.
- **`CHANGELOG.md:60`'s link to this package's `design.md` — stale**, broken by the later
  archiving commit (correct at merge time).
- **This review's own line citations have drifted** against current `render.py` line numbers —
  cosmetic, but means the evidence above can no longer be re-checked mechanically without
  re-deriving the line numbers first.

**Pass 2 — adversarial.** Nine attacks refuted (fail-closed by design: disabling pytest-cov,
`readonly` env tricks, function-local `unset` shadowing, empty-string override, vacuous
fixtures, `PYTHONPATH` shadowing, unrelated-content regeneration — all checked against the
real scripts, not assumed). Nine held:

1. **`COVERAGE_RCFILE` is an unclosed env lever of exactly the class this change closes — the
   one live gate-integrity hole found.** 6 of 7 generated `do_coverage()` bodies pass no
   `--cov-config`, so pytest-cov falls through to coverage.py's `COVERAGE_RCFILE`
   environment-variable fallback; a pointed-at rc file with a broad `exclude_lines`/`omit` can
   drive measured coverage to ~100% with no notice and no `unset`. Zero repo-wide mentions of
   `COVERAGE_RCFILE` anywhere in this change's docs or residual-risk list. Root's `do_extra()`
   is incidentally immune (`--cov-config=scripts/.coveragerc` is explicit there). Fix is one
   line: add `--cov-config=` to `_coverage_command`, or fold into a general env-scrub.
2. Root's `do_extra()` guard is dead on its only reachable call path — `do_coverage` (which
   `do_all` always runs first) already clears `PYTEST_ADDOPTS` globally, so `do_extra`'s own
   notice/unset can never fire. The prior review's refutation of this same attack sourced
   `do_extra` standalone, a path the shipped script cannot take. Real defense-in-depth against
   *future* reordering, not what closes the evasion today.
3. `F_054.py` asserts `unset PYTEST_ADDOPTS` presence/count, never ordering — moving it after
   the `pytest` call in the one hand-maintained region it can't police passes F-054 unchanged.
4. `F_054.py`'s regex check is presence-only (never asserts the old unanchored pattern is
   *absent* — re-adding it silently restores the vulnerability) and its checked-package list
   omits `claude-foundation`, which does declare an (already-anchored) exclusion.
5. The two-anchor floor cross-check degrades silently to one anchor if a regex stops matching
   — the exact failure class this change discovered, fixed as a one-time value update rather
   than a structural `len(anchors) == 2` assertion.
6. `PYTHON=` remains a strictly stronger, still-live total bypass — correctly out of scope for
   this layer, but not carved out of `spec.md`'s absolute capability sentence (ties to the
   REFUTED claim above).
7. `F_054.py`'s `expected_unsets` count is a brittle proxy in both directions (a legitimately
   coverage-less package misreports its own failure cause; an extra unguarded pytest call in
   `do_extra` doesn't trip the count).
8. The committed floor literal's only other guard (`test_floor_anchors_agree_with_each_other`)
   is the same check weakened by finding 5 above — a hand-edited `--cov-fail-under=0` in a
   committed script passes every other test.
9. The `COV_FAIL_UNDER=0` positive control discriminates via a pytest-cov int-vs-float
   formatting accident (`"90%"` vs `"90.0%"`), not a structural assertion that the CLI flag is
   actually present — would silently stop discriminating if that formatting ever normalized.

### New follow-ups from this pass (none blocking; ranked)

1. **Confirm and close `COVERAGE_RCFILE`** (attack 1, above) — the one live gate-integrity
   hole, not a docs or enforcement gap.
2. **Fix the four documentation defects**: the false "single-source" claim, the two
   non-existent-code citations in `design.md`, `spec.md`'s over-broad capability sentence, and
   `SKILL.md`'s "notice either way" claim.
3. **Correct the record on the original review's attack (b)** — the `do_extra` guard is
   defense-in-depth, not what closed the evasion.
4. **Strengthen the guards that guard the guards**: an ordering assertion in `F_054.py`, an
   absence-of-unanchored-pattern check plus `claude-foundation` added to
   `_ANCHORED_REGEX_PYPROJECTS`, and a structural two-anchor assertion in `test_e2e_matrix.py`.

Follow-up 1 is tracked in `NEXT_STEPS.md` (merge-gate/quality-gate tech-debt section) rather
than fixed here — this pass is dogfood proof for `add-foundation-reviewer-charters`'s task 4,
not a license to re-open an already-archived, already-shipped change's scope.

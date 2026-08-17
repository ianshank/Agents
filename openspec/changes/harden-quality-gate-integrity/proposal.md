# Change: harden-quality-gate-integrity

**Status:** proposed · **Date:** 2026-08-17 · **Author track:** `claude/` agent lane
**Motivated by:** a file-by-file comparison of this repo's Claude Code tooling against a
sibling project (`docs/plans/orbital-drift-alignment/PLAN.md`), independently fact-checked
against the actual code rather than trusted — the comparison's own claims were wrong twice
(this repo already has a 32-entry ADR system and single-command local/CI parity), but reading
`skills/quality-gate/scripts/gategen/render.py` and its four downstream `pyproject.toml`
consumers directly surfaced two live, independently-confirmed coverage-gate evasions that
have nothing to do with the sibling project's own content.
**Compiles down to:** this OpenSpec package + `scripts/validations/F_054.py` (F-ID claimed at
land) + the errata already recorded in `docs/decisions/0009-tech-debt-audit-and-compat-surface.md`
(a factual correction to already-decided intent, not a new decision — no superseding ADR).

## Why

`skills/quality-gate/scripts/gategen/render.py` generates `scripts/quality-gate.sh` — the
single script CI and `make check` both call for lint, type-check, tests, and a coverage
threshold (module docstring, `render.py:1-11`). Before this change, that gate could be made to
report green without the underlying code actually meeting its coverage bar, in four
independently exploitable ways, all confirmed by reading the pre-change file
(`git show HEAD~1:skills/quality-gate/scripts/gategen/render.py` from this change's own
commit, or the brief that scoped this work):

1. **`COV_FAIL_UNDER` was a live, unguarded environment override.** `_variables()` emitted
   `COV_FAIL_UNDER="${COV_FAIL_UNDER:-<n>}"` unconditionally whenever a coverage step existed
   (old `render.py:183`), and `_coverage_command()` interpolated it as
   `--cov-fail-under="$COV_FAIL_UNDER"` (old `render.py:130`). Running
   `COV_FAIL_UNDER=0 ./scripts/quality-gate.sh coverage` made every package's coverage gate
   trivially pass. No `unset`, no warning — zero `unset` statements existed anywhere in the
   generated script.
2. **`COVERAGE_SOURCE` had the identical problem in the single-source case.** The multi-source
   branch of `_coverage_command()` already guarded against this
   (`prefix = [_ignored_override_notice("COVERAGE_SOURCE")]`, old `render.py:127`) — a real,
   working pattern — but the single-source branch silently honored a live override
   (`cov = '--cov="$COVERAGE_SOURCE"'`, old `render.py:123`). Every one of the 7 packages this
   generator serves uses single-source coverage, so the *majority* code path had no guard at
   all. Pointing `COVERAGE_SOURCE` at a narrow or trivially-covered subtree would inflate the
   reported percentage exactly like finding 1.
3. **`PYTEST_ADDOPTS` passed through to pytest completely unguarded.** The generated script
   never read it, warned on it, or cleared it, so any coverage-weakening flag set in the
   environment (`--no-cov`, `-k`, `--override-ini`) silently applied to every pytest
   invocation the gate made.
4. **The coverage-exclude regex was inconsistent across packages, contradicting its own
   governing decision doc's claim that it was aligned.** Root `pyproject.toml` (`exclude_lines`,
   line 185) and `scripts/.coveragerc` (`exclude_lines`, line 20) used the anchored pattern
   `"^\s*\.\.\.$"` — only a line that is *entirely* whitespace + ellipsis.
   `agent-core/pyproject.toml`, `behavioral-regression/pyproject.toml`,
   `flow-protocol/pyproject.toml`, and `flow-corpus/pyproject.toml` all used the unanchored
   `"\.\.\."` instead, under `[tool.coverage.report] exclude_also`. `coverage.py` matches
   `exclude_also`/`exclude_lines` patterns with `re.search`, not a full-line match, so the
   unanchored form silently excluded **any line containing three consecutive dots** — not
   just a standalone `Protocol`/abstract-method stub body, but potentially real code such as
   `arr[..., 0]` or a docstring fragment. `docs/decisions/0009-tech-debt-audit-and-compat-surface.md`
   (§4, "the root `exclude_lines` was aligned with the sub-packages'") claimed these patterns
   were aligned — true in intent, false in the regex text, in 4 of the 5 packages checked.

A fifth, structural gap made all four invisible: **no positive-control test existed anywhere**
that planted a deliberately low-coverage module and asserted the *real* generated gate script
actually fails. `skills/quality-gate/tests/test_gen_gate.py`'s existing fixtures hardcode
`fail_under=0` in their synthetic `pyproject.toml` (`_project()`, pre-change
`tests/test_gen_gate.py:59`), so nothing in the suite could ever demonstrate the threshold
does anything at all, let alone that it resists the four evasions above.

## What changes

- **`skills/quality-gate/scripts/gategen/render.py`**: `_coverage_command()` now interpolates
  `facts.cov_fail_under` and `facts.coverage_source` as **generation-time literals** in both
  the single- and multi-source branches — `--cov-fail-under=95`, never
  `--cov-fail-under="$COV_FAIL_UNDER"` — and unconditionally emits
  `_ignored_override_notice("COVERAGE_SOURCE")` and `_ignored_override_notice("COV_FAIL_UNDER")`
  (a stderr warning, exit code unaffected) so a live override is visible, not silently
  swallowed. `_variables()` no longer declares either variable — there is nothing left to
  override. A new `_pytest_addopts_guard()` helper emits a warn-then-`unset` pair
  (`quality-gate: PYTEST_ADDOPTS is ignored; this stage is a gate and has no opt-out`) ahead of
  every pytest invocation the gate makes — `do_test` (via `_step_commands()`) and `do_coverage`
  (via `_coverage_command()`) both carry it, since pytest reads `PYTEST_ADDOPTS` natively and a
  warning alone would not stop it from taking effect.
- **All 7 generated `scripts/quality-gate.sh` copies** (root, `agent-core/`,
  `behavioral-regression/`, `claude-foundation/`, `experiments/backend-validation/`,
  `flow-corpus/`, `flow-protocol/`) regenerated from the fixed generator via each file's own
  `# regenerate:` provenance comment — never hand-patched.
  `skills/project-setup/evals/fixtures/with-gate/scripts/quality-gate.sh` is a frozen test
  fixture and is deliberately untouched.
- **Root `scripts/quality-gate.sh`'s hand-maintained `do_extra()`** (below the marker, out of
  the generator's reach by design) invokes pytest directly for the `scripts/` coverage gate —
  hand-edited to carry the identical `PYTEST_ADDOPTS` guard, so the evasion is closed there too.
- **The coverage-exclude regex** in `agent-core/pyproject.toml`, `behavioral-regression/pyproject.toml`,
  `flow-protocol/pyproject.toml`, and `flow-corpus/pyproject.toml` changed from `"\.\.\."` to
  `"^\s*\.\.\.$"`, matching root/`scripts/.coveragerc`'s already-safe pattern exactly. Verified
  empirically, not just asserted: each package's **full** test suite was re-run with the fixed
  pattern (`--cov-branch --cov-report=term-missing`) and stayed comfortably above its
  `fail_under` floor — `agent-core` 98.49%/95%, `behavioral-regression` 100%/95%,
  `flow-corpus` 100%/95%, `flow-protocol` 100%/95%. The one-line `Protocol`/callback stub form
  this repo also uses (`def foo(self) -> int: ...`, e.g. `agent-core/agent_core/protocols.py`)
  does not regress under the anchored pattern: coverage.py already marks a one-line `def`'s
  sole physical line as executed at class/module-definition time regardless of whether the
  method is ever called, so removing it from the exclude set adds a handful of always-hit
  statements (and, under branch coverage, a small number of partial-branch notes) rather than
  new misses — confirmed by direct experiment, not assumed.
- **`docs/decisions/0009-tech-debt-audit-and-compat-surface.md`** gets an `**Errata**` line
  (placed and worded per `docs/decisions/0032-matrix-completeness-policy.md`'s existing
  pattern) recording that its §4 "aligned" claim was true in intent, false in the regex text,
  until this change.
- **`tests/_e2e_matrix.py`'s `_floor_from_gate_script()`** (not named in scope by the initial
  brief, found by tracing every consumer of the old `COV_FAIL_UNDER="${COV_FAIL_UNDER:-N}"`
  string before deleting it): its regex matched only the pre-hardening variable-declaration
  form. Left unfixed, it would have silently returned `None` for every package once the
  generator stopped emitting that form — collapsing `tests/test_e2e_matrix.py`'s
  `test_floor_anchors_agree_with_each_other` (`ROOT`-scoped, asserts a pyproject floor and its
  generated gate script state the same number) from a real two-source cross-check down to a
  single-source read that would still trivially "pass" with only one anchor left. Updated to
  match the new `--cov-fail-under=N` literal; the two-anchor agreement was re-verified directly
  (`em.derive_packages(...)` against the real regenerated tree) rather than trusted from the
  test's green alone.
- **`skills/quality-gate/SKILL.md`** §2 step 6 and the output contract (§3) corrected: they
  documented `COVERAGE_SOURCE`/`COV_FAIL_UNDER` as `${VAR:-default}`-overridable in
  single-source mode, which is now false by design. `skills/quality-gate/evals/evals.json`'s
  `generate-gate` case assertion updated from the old `--cov-fail-under="$COV_FAIL_UNDER"`
  text to the new literal, plus two new assertions for the ignored-override and
  `PYTEST_ADDOPTS` notice text. Skill version bumped `1.1.0` → `1.2.0` in `SKILL.md`
  frontmatter and `skills/marketplace.yaml` (byte-matched, `skill_marketplace.py validate`).
- **Positive-control tests** added to `skills/quality-gate/tests/`: a genuinely low-coverage
  fixture package whose *real* rendered `quality-gate.sh coverage` fails with coverage.py's own
  "Required test coverage ... not reached" text; a high-coverage fixture that exits 0; the
  low-coverage fixture with `COV_FAIL_UNDER=0` injected into the subprocess environment still
  failing (closes finding 1); the same fixture with a coverage-weakening `PYTEST_ADDOPTS` still
  failing (closes finding 3). These shell out to the real rendered script and real pytest —
  no mocking the outcome, since the outcome is the entire point.
- **`scripts/validations/F_054.py`** (new, read-only, static): confirms all 7 regenerated
  scripts carry the three ignored-override notices and no longer interpolate raw
  `"$COV_FAIL_UNDER"` or single-source `"$COVERAGE_SOURCE"` into the pytest-cov invocation, and
  that all 4 corrected `pyproject.toml` files carry the anchored regex. `features.yaml` gains
  the corresponding F-054 row.

## Scope / non-goals

- **Non-goal: `TYPECHECK_PATHS`'s single-path env-override behavior.** It is a documented
  debug affordance for a non-thresholded check (overriding it changes *what* gets
  type-checked, not *whether* a numeric gate can be gamed) — `_typecheck_commands()` and
  `_typecheck_env_form()` are untouched, and the single-path `${TYPECHECK_PATHS:-...}`
  declaration in `_variables()` still stands.
- **Non-goal: a second env-clearing layer in `.github/actions/run-quality-gate/action.yml`.**
  Verified the action sets neither `COV_FAIL_UNDER` nor `COVERAGE_SOURCE` anywhere
  (`action.yml:1-38`) — the generator is the single source of truth every consumer gets on
  regeneration; a second place to keep in sync buys no added safety and was explicitly
  declined in `docs/plans/orbital-drift-alignment/PLAN.md`'s Phase 1 table.
- **Non-goal: `skills/project-setup/scripts/makegen/render.py`.** This is a *different*
  generator (produces a `Makefile`, not `quality-gate.sh`) belonging to a different skill, and
  it has the analogous problem — `COVERAGE_SOURCE ?= ...` / `COV_FAIL_UNDER ?= ...` are live
  Make-variable overrides (`makegen/render.py:130-131`). Found while tracing every consumer of
  the vulnerable pattern, but out of scope: neither the originating brief nor
  `docs/plans/orbital-drift-alignment/PLAN.md`'s Phase 1 file list names it, and a Makefile's
  override idiom (`?=`) is a different mechanism needing its own design pass, not a drive-by
  fix bundled into this change. Recorded here so it is not lost track of.
- **Non-goal: retroactively re-auditing every other `exclude_lines`/`exclude_also` entry.**
  Only the specific `"\.\.\."` → `"^\s*\.\.\.$"` divergence identified against the ADR 0009
  "aligned" claim is in scope; the other four exclude patterns (`pragma: no cover`,
  `if TYPE_CHECKING:`, `raise NotImplementedError`, `if __name__ ==`) were already identical
  in substance across all packages and are unaffected.
- **Non-goal: a mandatory second ADR.** The errata in `docs/decisions/0009-...md` is a factual
  correction to already-decided intent (the regex text did not match what the ADR said it
  did), not a course change, per `docs/decisions/README.md`'s "immutable once accepted" rule
  and the precedent in `docs/decisions/0032-matrix-completeness-policy.md`'s own Errata block.

## Impact

- **Protected paths touched:** `tests/**` (`tests/_e2e_matrix.py`,
  `skills/quality-gate/tests/**` — the quality-gate skill's own test suite is not under root
  `tests/**` but is treated with the same review discipline), `features.yaml`,
  `scripts/validations/**` (new `F_054.py`). Implementation carries the
  `eval-change-approved` label per `scripts/eval_protected_paths.py`.
- **Coverage floors verified, not assumed:** `agent-core`/`behavioral-regression`/
  `flow-protocol`/`flow-corpus` at 95% (per-package `pyproject.toml`), root `eval_harness` at
  96%, `scripts/` at 85% (`scripts/.coveragerc`) — all re-run in full against the changed
  files in this change and confirmed green (see `tasks.md` Verification for exact figures).
- **Skill-facing surface:** `quality-gate` skill version `1.1.0` → `1.2.0`
  (`skills/quality-gate/SKILL.md`, `skills/marketplace.yaml`); no change to the skill's CLI
  flags, only to the generated artifact's runtime behavior and documented contract.
- **No engine, core-model, or registry change** — this is entirely within the `quality-gate`
  skill's generator, its 7 downstream artifacts, 4 packages' coverage config, one ADR errata,
  and the governance/test surface that proves the fix. `architecture.yaml` is unaffected.

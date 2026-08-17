# Tasks: harden-quality-gate-integrity

`[P]` = protected path; needs `eval-change-approved` label + CODEOWNERS review.
Coverage floors touched by this change: root/`eval_harness` **96%**, `agent-core`/
`behavioral-regression`/`flow-protocol`/`flow-corpus` **95%**, `scripts/` **85%**
(`scripts/.coveragerc`), `skills/quality-gate` (`gategen`) **95%**.

## 1. Generator fix — `skills/quality-gate/scripts/gategen/render.py`

- [x] `_coverage_command()`: interpolate `facts.cov_fail_under` and `facts.coverage_source` as
      generation-time literals in **both** the single- and multi-source branches; no
      `"$COV_FAIL_UNDER"` or single-source `"$COVERAGE_SOURCE"` reference remains anywhere in
      the emitted pytest-cov invocation.
- [x] `_coverage_command()`: unconditionally emit `_ignored_override_notice("COVERAGE_SOURCE")`
      and `_ignored_override_notice("COV_FAIL_UNDER")` ahead of the pytest-cov call, in both
      branches — not just the pre-existing multi-source `COVERAGE_SOURCE` case.
- [x] New `_pytest_addopts_guard()`: warn (`quality-gate: PYTEST_ADDOPTS is ignored; this stage
      is a gate and has no opt-out`, to stderr) then `unset PYTEST_ADDOPTS`, in the same shell
      idiom as `_ignored_override_notice`.
- [x] Wire the guard into **both** pytest-invoking steps: `_step_commands()`'s `"test"` entry
      and `_coverage_command()`'s return value.
- [x] `_variables()`: remove the `COVERAGE_SOURCE="${COVERAGE_SOURCE:-...}"` and
      `COV_FAIL_UNDER="${COV_FAIL_UNDER:-...}"` declarations entirely (dead once nothing
      references them).
- [x] Explicitly untouched: `_typecheck_commands()`, `_typecheck_env_form()`, and the
      single-path `TYPECHECK_PATHS` declaration in `_variables()` — out of scope per
      `proposal.md`.
- [x] `skills/quality-gate/tests/test_render.py` updated for the new literal/notice shape
      (single- and multi-source cases) and extended with `PYTEST_ADDOPTS`-guard-specific unit
      tests (`do_test`/`do_coverage`, guard-before-pytest ordering, message text).

## 2. Regeneration — 7 `quality-gate.sh` copies

- [x] Regenerated via each file's own `# regenerate:` provenance comment (`gen_gate.py`), not
      hand-patched: root, `agent-core/`, `behavioral-regression/`, `claude-foundation/`,
      `experiments/backend-validation/`, `flow-corpus/`, `flow-protocol/`.
- [x] `skills/project-setup/evals/fixtures/with-gate/scripts/quality-gate.sh` (frozen fixture)
      confirmed untouched (`git status` shows no diff for it).
- [x] Root's hand-maintained `do_extra()` (below the marker, generator-unreachable by design)
      hand-edited to carry the identical `PYTEST_ADDOPTS` warn-then-`unset` guard ahead of its
      direct `pytest` invocation.
- [x] `python skills/quality-gate/scripts/gen_gate.py --check` (with each package's own
      `--typecheck-path` flags from its `# regenerate:` line) confirms all 7 round-trip as
      "up to date" against the fixed generator.

## 3. Coverage-exclude regex — 4 `pyproject.toml` files

- [x] `agent-core/pyproject.toml`, `behavioral-regression/pyproject.toml`,
      `flow-protocol/pyproject.toml`, `flow-corpus/pyproject.toml`: `exclude_also` entry
      `"\.\.\."` → `"^\s*\.\.\.$"`, matching root `pyproject.toml`'s `exclude_lines` and
      `scripts/.coveragerc`'s already-correct pattern (syntax/quoting matched exactly per
      file's own convention — TOML double-backslash for the two `pyproject.toml`-style files,
      unchanged elsewhere).
- [x] Verified **empirically** the tightened pattern does not newly fail any of the 4 floors:
      full `pytest --cov=<pkg> --cov-branch --cov-report=term-missing` run per package (see
      `proposal.md` Impact and this file's Verification section for the real numbers).
- [x] Investigated the one-line `Protocol`/callback stub form (`def foo(...) -> T: ...`, e.g.
      `agent-core/agent_core/protocols.py`) that the unanchored pattern used to swallow and the
      anchored pattern does not — confirmed by direct experiment (see `design.md`) that
      coverage.py already marks such a line as executed at class/module-definition time
      regardless of whether the method is called, so no new *line* misses are introduced.

## 4. Positive-control tests — `skills/quality-gate/tests/`

- [x] `[P]` Low-coverage fixture package (a real module with an intentionally uncovered
      branch/function) whose rendered `quality-gate.sh coverage`, actually executed via
      `subprocess`, exits non-zero and prints coverage.py's own
      "Required test coverage ... not reached" text.
- [x] `[P]` High-coverage fixture (same shape, fully exercised) whose rendered
      `quality-gate.sh coverage` exits 0.
- [x] `[P]` The low-coverage fixture re-run with `COV_FAIL_UNDER=0` injected into the
      subprocess environment **still fails** — the finding-1 evasion is closed.
- [x] `[P]` The low-coverage fixture re-run with a coverage-weakening `PYTEST_ADDOPTS`
      (`--no-cov`) injected into the subprocess environment **still fails** — the finding-3
      evasion is closed.
- [x] None of the four mock the outcome: each shells out to the real rendered script and real
      installed `pytest`/`coverage`.

## 5. Cross-cutting consumers found while removing the old string

- [x] `[P]` `tests/_e2e_matrix.py::_floor_from_gate_script`: regex updated from the
      variable-declaration form to the new `--cov-fail-under=N` literal form.
- [x] `[P]` `tests/test_e2e_matrix.py::TestDerivation::test_floor_anchors_agree_with_each_other`
      re-verified against the real, regenerated tree (`em.derive_packages(...)` inspected
      directly) to confirm it still checks **two** independent anchors per package, not one
      anchor left silently unmatched.

## 6. Docs and skill registration

- [x] `skills/quality-gate/SKILL.md` §2 step 6 and §3 (output contract): corrected the
      overridability claim for `COVERAGE_SOURCE`/`COV_FAIL_UNDER`; documented the
      `PYTEST_ADDOPTS` guard.
- [x] `skills/quality-gate/evals/evals.json`: `generate-gate` case's coverage-threshold
      assertion updated to the literal form; two new assertions added (ignored-override notice
      text, `PYTEST_ADDOPTS` notice text). Verified by hand-running the eval's own `gen_gate.py`
      invocation against `evals/fixtures/full/` and grepping the output for each assertion string.
- [x] `skills/quality-gate/SKILL.md` frontmatter `version` and `skills/marketplace.yaml`'s
      `quality-gate` entry both bumped `1.1.0` → `1.2.0` (byte-matched).
- [x] `docs/decisions/0009-tech-debt-audit-and-compat-surface.md`: `**Errata**` line added
      (placement/wording modeled on `docs/decisions/0032-matrix-completeness-policy.md`'s
      existing Errata block) — factual correction to already-decided intent, no superseding ADR.

## 7. Governance — `[P]`

- [x] `[P]` Claimed F-054 in `features.yaml` (next free number after F-053).
- [x] `[P]` `scripts/validations/F_054.py`: read-only, static, no test execution (style matches
      `F_031.py`) — asserts all 7 regenerated scripts carry the three ignored-override
      notices, no raw `"$COV_FAIL_UNDER"`/single-source `"$COVERAGE_SOURCE"` interpolation
      remains in any pytest-cov invocation, and all 4 `pyproject.toml` files carry the
      anchored regex.
- [x] CHANGELOG entry under `[1.3.0-dev] — Unreleased`.
- [x] `openspec/README.md` "Current changes" gains a `harden-quality-gate-integrity` row (its
      own guard requires every non-archived `changes/` directory to appear there).

## 8. Verification

Real output captured, not asserted — see the implementing agent's final report for the exact
pass/fail lines. Every one of the 7 packages' REAL regenerated `quality-gate.sh` was executed
(not just the generator's unit tests) — including a single-invocation `./scripts/quality-gate.sh
all` for root, `behavioral-regression`, `flow-corpus`, and `flow-protocol`.

- [x] `cd skills/quality-gate && python -m pytest tests --cov=gategen --cov-branch
      --cov-fail-under=95 -q` — 78 passed, 99.65% coverage
- [x] `python scripts/validate.py --tier fast` (exercises the new F_054 check) — 52 done, all
      passed including F-054
- [x] `python scripts/check_skill_script_drift.py` — 16/16 vendored copies match
- [x] `python skills/quality-gate/scripts/gen_gate.py --check` against all 7 target
      directories (each package's own `--typecheck-path` flags) — all 7 "up to date"
- [x] Root: full `./scripts/quality-gate.sh all` (lint, typecheck, coverage, and the
      hand-edited `do_extra()` scripts-coverage stage, one invocation) — PASS; coverage
      96.98%/96% (1625 passed, 41 skipped), scripts-coverage 93.35%/85% (same run)
- [x] `agent-core`: `lint`/`typecheck`/`coverage` run individually through the real
      regenerated script — all green; coverage 98.49%/95% (788 passed, 2 xfailed)
- [x] `behavioral-regression`: full `./scripts/quality-gate.sh all`, one invocation — PASS;
      100%/95% (157 passed)
- [x] `claude-foundation`: `lint`/`typecheck`/`coverage` run individually through the real
      regenerated script — all green; coverage 96.03%/85% (136 passed)
- [x] `flow-corpus`: full `./scripts/quality-gate.sh all`, one invocation — PASS; 100%/95%
      (163 passed)
- [x] `flow-protocol`: full `./scripts/quality-gate.sh all`, one invocation — PASS; 100%/95%
      (21 passed)
- [x] `experiments/backend-validation`: `lint`/`coverage` run individually through the real
      regenerated script — both green; coverage 97.72%/95% (355 passed). `typecheck` fails on
      a **pre-existing, unrelated** `types-jsonschema` stub-package gap in this environment
      (`backend_validation/metrics.py:17`, `phases.py:18`) — declared in this package's own
      `pyproject.toml` dev extras but not installed in the sandbox this change was verified
      in; `_typecheck_commands`/`_typecheck_env_form` are untouched by this change, so this is
      an environment gap, not a regression it introduced.

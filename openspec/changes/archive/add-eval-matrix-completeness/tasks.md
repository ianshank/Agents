# Tasks: add-eval-matrix-completeness

`[P]` = protected path; needs `eval-change-approved` + CODEOWNERS review.
Coverage floors: root `eval_harness` **96%**; operational scripts **85%**.

**PR shape.** `scripts/eval_protected_paths.py` protects root `tests/**`, `config/**`,
`features.yaml`, `scripts/validations/**` and `.github/**` — nearly every file below is
`[P]`. Strict per-PR protected isolation would strand test-only commits below the coverage
floors, so use the PR #82 shape: **one labelled PR, protected changes isolated into their own
commits** (each commit green standalone).

## 0. Spec (this PR, unlabelled — `openspec/**` and `docs/decisions/**` are unprotected)
- [x] `proposal.md` / `design.md` / `tasks.md` / `review.md` / `specs/eval-matrix/spec.md`.
- [x] Linked bullet in `openspec/README.md` "Current changes" (target exactly
  `changes/add-eval-matrix-completeness/` — the docs.yml index guard matches link targets).
- [x] [ADR 0032](../../../../docs/decisions/0032-matrix-completeness-policy.md) authored as
  *Proposed*.

## 1. Trajectory rows + M8 pipelines + shipped-config fix — commit 1
- [ ] `[P]` Seven per-scorer matrix classes + one shared parametrized class in
  `tests/test_matrix_eval_tools.py`, each carrying literal `MATRIX_KIND` /
  `MATRIX_COMPONENTS` tuples. M1 = the discriminating scenario per scorer; assertions on
  `passed`/`value`, never `comment` (an args-only mismatch renders identical name lists).
- [ ] `[P]` Shared M2 (missing trajectory → `passed is None`; `on_missing` override; missing
  reference; empty steps), M3, M5 (repeat-scoring identity on a set-bearing trajectory;
  cross-process canonicalisation stays pinned in `test_trajectory_contracts.py`), M6
  (verified error paths incl. `on_missing="abc"` — the ValueError case is a non-numeric
  *string* — and unknown-kwarg TypeError, already pinned in `test_trajectory_integration.py`).
- [ ] `[P]` `PIPELINES` module constant; M8 tests parametrize over it and run the configs;
  the trajectory pipeline spells full reference arguments (names-only fails under the
  `compare_arguments: True` default) and asserts `output.error is None` (the callable target
  swallows SUT exceptions into `TargetOutput.error`).
- [ ] `[P]` Fix `config/trajectory_eval.yaml` reference arguments so the shipped example
  passes its own gate; strengthen the covering test to run it and assert the gate PASSES.

## 2. Derived M7 + alias freeze + sparse fills — commit 2
- [ ] `[P]` Rewrite `TestM7Registry`: parametrize over `tests/plugin_registry_baseline.json`,
  asserting `key in registry` and `registry.resolve(key) in registry.names()` (aliases are
  not in `names()`). Docstring scopes why this direction is in-process-safe.
- [ ] `[P]` Per-kind exact-equality alias→canonical assertion against `FROZEN_ALIAS_MAP`.
- [ ] `[P]` Sparse fills to the ADR 0032 floors (scorers +M3/M5/M6; judges +M2/M3/M6;
  datasets +M2/M3/M6; targets +M2/M3/M6 with the echo-M6 waiver; sinks: one parametrized
  empty-run M2 over all six + per-sink M6 degrade/error; gating +M6 — unknown `metric` is a
  `pydantic.ValidationError` via field_validator, absent score fails the gate with a reason).
- [ ] `[P]` `MATRIX_KIND`/`MATRIX_COMPONENTS` on every existing component class;
  `MATRIX_KIND = "gating"` on `TestGating`; M8 methods renamed to carry the `m8` prefix.

## 3. Guard + generator — commit 3
- [ ] `[P]` `tests/_matrix_coverage.py`: AST extractor, cached subprocess census
  (`{kind: {names, aliases}}`), `REQUIRED_DIMS`/`EXTRA_SUITES`/`WAIVED`/`FOLLOW_ON`/
  `FROZEN_ALIAS_MAP` single-sourced, `render_doc()` (deterministic; py3.10-safe).
- [ ] `[P]` `tests/test_matrix_coverage.py`: policy floors both directions, waiver +
  obligation hygiene both ways, alias freeze, M8 kind coverage, doc freshness, guard
  self-tests (probe timeout/exit/garbled; extractor vacuity), `__main__ --check/--update`.

## 4. Docs — commit 4 (unprotected)
- [ ] Generated `docs/matrix-coverage.md`; `mkdocs.yml` nav entry under `Architecture:`.
- [ ] Flip ADR 0032 → Accepted; row in `docs/decisions/README.md`.
- [ ] CHANGELOG entry; `NEXT_STEPS.md` — reword the F-045 xlsx claim (never committed; not to
  be conflated with `experiments/backend-validation`'s *external* matrix workbook) and fold
  the F-ID-less "Hardened matrix eval tools test suite" bullet under this feature.

## 5. Ledger + proof — commit 5
- [ ] `[P]` `features.yaml` F-0NN entry (claimed at land; `status: in_progress` in this
  commit), verification bullets each naming `(F_0NN.py)` with mutation clauses.
- [ ] `[P]` `scripts/validations/F_0NN.py` — imports the extractor/policy from
  `tests/_matrix_coverage.py` (F-052's no-restatement principle); checks: `--check` exits 0,
  doc exists with the GENERATED header, designated registry classes contain no all-literal
  parametrize, `eval-harness-ci.yml` paths include the doc.
- [ ] `[P]` Hook into `tests/test_validation_scripts.py` (explicit import + parametrize +
  ids); repair the missing `F_052` import there; fix its stale "(F_020..F_023)" docstring.

## 6. CI wiring + ledger flip — commit 6
- [ ] `[P]` `eval-harness-ci.yml`: add `docs/matrix-coverage.md` to `push.paths` and
  `pull_request.paths` (a hand edit to the generated doc must trigger the freshness test).
- [ ] `[P]` `quality-gates.yml` tooling-coverage step: append the new validator's `--cov=`;
  the dead `--cov=F_052` becomes live via the commit-5 import repair.
- [ ] `[P]` Flip F-0NN to `done` with `implemented_in` = the commit-5 SHA (the commit that
  added both the ledger entry and the proof — the `ae1cfc6` derivation, without
  self-reference).

## 7. Post-merge follow-up (unlabelled)
- [ ] Archive this change (`git mv` to `changes/archive/`), stamp
  `**Status:** landed — F-0NN @ <merge sha10>`, fix relative links one level deeper, move the
  README bullet into the Archived table.

## 8. Verification
- [ ] `make check` · `python tests/test_matrix_coverage.py --check` ·
  `python scripts/validations/F_0NN.py` · `python scripts/validate.py --tier fast --strict` ·
  `python scripts/check_charter_drift.py` · `python scripts/check_charter_invariants.py` ·
  `python scripts/check_size_budget.py` · `python scripts/check_guard_reachability.py`.
- [ ] Baseline no-ops: both `--update` runs (`test_public_surface.py`,
  `test_plugin_registry_surface.py`) produce no diff; discard.
- [ ] Mutation checks: delete one trajectory class → "no matrix rows"; hand-edit the doc →
  freshness red; bogus waiver → "stale waiver"; satisfied `FOLLOW_ON` row → "remove the row";
  repoint an alias (scratch) → alias-map assertion red.

# Change: extend-matrix-to-fleet

**Status:** proposed · **Date:** 2026-09-08 · **Author track:** agent lane
**Motivated by:** `docs/plans/eval-evidence-integrity/PLAN.md` Phase 9.
**Compiles down to:** ADR 0032 §6 amendment + `tests/_fleet_matrix.py`.

## Why

ADR 0032 §6 still called fleet extension future work. Phase 3 closed M8 semantics
(F-063); Phase 8 residual is the e2e provenance gate. Fleet scale is next, not XOR with
WS-1.

No sibling package has `MATRIX_KIND`. Inventing floors would fabricate coverage. This
change installs the *census* with two mechanisms and cross-checks hand declarations against
each package's frozen public-surface baseline.

## What changes

- `tests/_fleet_matrix.py`: derive `CALIBRATOR_FACTORIES` (exclude `CalibratorRegistry`)
  and flow-corpus `SPECIMENS.register` names via AST; hand-declare behavioral-regression,
  flow-protocol, and claude-foundation against their baselines.
- ADR 0032 §6 amendment describing the two mechanisms.
- Skills `EXEMPT` collapsed to `skills/ci_exempt.yaml` (skills-ci + F-050). The docs.yml
  README EXEMPT list is a different list and is not merged.
- Phase 10 M2/M6 negative controls in `tests/test_matrix_coverage_guards.py`.

## Scope / non-goals

- Non-goal: `MATRIX_KIND` rows in sibling test suites (that is a later depth pass).
- Non-goal: putting `skills-ci` in the required-check set (needs ADR 0040 stubs first).
- Non-goal: WS-1 / production flywheel.
- Non-goal: fabricating per-package dim floors.

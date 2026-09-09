# Review: extend-matrix-to-fleet

**Date:** 2026-09-08 · **Track:** agent lane · **Status:** implementation in this PR

## Pass 1 — spec vs tree

- Derived census: `CALIBRATOR_FACTORIES` via AST (`AnnAssign` included; `CalibratorRegistry`
  excluded) and flow-corpus `SPECIMENS.register`. Derived packages check that the
  **registry symbol** is in the frozen baseline, not the factory keys.
- Hand declarations for behavioral-regression, flow-protocol, and claude-foundation
  are subsets of those packages' frozen surfaces.
- Skills `EXEMPT` is `skills/ci_exempt.yaml` (F-050 + skills-ci). docs.yml README EXEMPT
  is a different list.
- Phase 10 canaries assert on the missing side of `split("(have")` so `'M5'` in the
  `(have …)` clause cannot mask a missing M2/M6.

## Pass 2 — what this does not do

Does not add `MATRIX_KIND` rows to sibling suites. Does not invent product coverage
floors. Does not put `skills-ci` in the required-check set.

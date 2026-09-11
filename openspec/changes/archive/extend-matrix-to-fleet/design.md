# Design: extend-matrix-to-fleet

## Two mechanisms (ADR 0032 §6)

**Derived.** agent-core: string keys of `CALIBRATOR_FACTORIES` parsed from
`recalibration.py`. `CalibratorRegistry` is a freeze-then-predict container, not a factory,
and is excluded by construction (it is not a dict key). flow-corpus: first arguments of
`SPECIMENS.register(...)`. AST-only so the root suite does not import sibling packages.

**Checked declaration.** behavioral-regression, flow-protocol, claude-foundation: a
literal tuple, each name required to appear in that package's
`public_surface_baseline.json` or `backwards_compat_baseline.json`. A declared name that is
not exported fails. We do not require the declaration to cover the entire surface — that
would force cosmetic `MATRIX_KIND` rows.

## Skills EXEMPT

`skills/ci_exempt.yaml` is the one importable source for the three ADR 0030 subjective
skills. `skills-ci.yml`'s all-skills job and `F_050.py` both read it. `docs.yml`'s EXEMPT
is a component-README list and stays separate.

## Phase 10 canaries

M2 and M6 negative controls live in `test_matrix_coverage_guards.py`. They construct a
component that meets every other floor dim and omit only M2 or only M6. M3/M5 are not
padded.

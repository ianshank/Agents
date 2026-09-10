# Change: repair-e2e-matrix-provenance

**Status:** implemented (archived; landed `27e5b8cb588569f021e8bc83b7592fa67be91015`) · **Date:** 2026-09-08 · **Author track:** agent lane
**Motivated by:** `docs/plans/eval-evidence-integrity/PLAN.md` Phase 8 residual +
`docs/e2e-matrix/ERRATA.md` (finding P1.9).
**Compiles down to:** ADR 0033 amendment + `tests/_e2e_matrix.py` provenance/monotonicity
helpers (no new F-ID; claimed at land if a validator is later warranted).

## Why

`tests/test_e2e_matrix.py --check` excludes the Provenance section from the markdown/CSV
comparison (ADR 0033 §3): gating SHA == HEAD is permanently red on the commit that carries a
fresh render. That exemption is correct. The gap is that nothing else asked whether the
stamped SHA is *reachable* (exists, is an ancestor of HEAD) or whether a new render dropped
observed-step / suite test counts. `3272006` committed a 1627→995 test-count drop with a
stamp that did not match `git show` of that SHA.

POSIX driver and nightly freshness already landed. This change is the integrity half.

## What changes

- Provenance gated as reachable and consistent: SHA exists and is an ancestor of HEAD, never
  equal-to-HEAD. A SHA missing from a shallow clone is skipped (not failed) so CI pytest
  never gates the live stamp.
- Monotonicity: `--update` refuses a render that drops observed steps or a suite's test count
  unless `MONOTONICITY_WAIVERS` names that exact (metric, previous, current) triple.
- Known-stale stamps in `PROVENANCE_SHA_WAIVERS` (ERRATA `09337aec…` and the POSIX restamp
  `0b2cbfb7…`) so the live artifact stays mergeable until the next full e2e `--update`.
- ADR 0033 amendment recording the narrowed exemption.

## Scope / non-goals

- Non-goal: regenerating `docs/e2e-matrix/` in this change (that needs a real run report).
- Non-goal: a pytest that reads the live committed SHA (shallow clones go red).
- Non-goal: equal-to-HEAD gating (ADR 0033 §3 survives).

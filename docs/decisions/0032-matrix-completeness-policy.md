# 0032 - Matrix-completeness policy: per-kind required dimensions, checked declarations, waivers, and a generated coverage artifact

**Status**: Accepted — lands with `openspec/changes/add-eval-matrix-completeness/` as
F-053 (`implemented_in` recorded in `features.yaml`; the archive entry carries the
landing SHA). Enforcement is live from the same change: the guard suite, the frozen
alias maps, and the freshness-gated artifact all ship with it.
**Date**: 2026-08-08

Related: [ADR 0024](0024-assertion-graders-registry.md) (registry dispatch over hand-rolled
loops), [ADR 0030](0030-skill-ci-tiers.md) (the derived-list + EXEMPT-with-reason
idiom this generalises), F-039 (`tests/test_public_surface.py` — surface baselines), F-050 and
F-052 (the manual-list-vs-derived-reality defect class this closes for the matrix),
`openspec/changes/add-eval-matrix-completeness/` (mechanism trade-offs in its `design.md`).

## Context and Problem Statement

`tests/test_matrix_eval_tools.py` declares itself the test matrix of "all eval tools ×
standardized metrics" (M1 Correctness, M2 Edge Cases, M3 Type Safety, M4 Interface,
M5 Determinism, M6 Error Handling, M7 Registry, M8 Composability), and `AGENTS.md` holds it up
as the offline-DI reference. But its component axis was hand-maintained: the M7 lists went
stale by seven scorers the day F-051 registered them, thirteen aliases were asserted nowhere,
and nothing failed. "Which components must the matrix cover, at which dimensions" was tribal
knowledge, so every new component silently shrank the matrix's honesty.

The repo has closed this defect class twice — F-050 derived the skills-CI job list from the
directory tree; F-052 derived guard reachability from the protected-pattern list — and both
times the fix was the same shape: derive the census, enforce a floor, make exemptions
explicit data with reasons.

## Decision

The matrix is governed by a single policy, single-sourced in `tests/_matrix_coverage.py` and
enforced by `tests/test_matrix_coverage.py`:

```python
REQUIRED_DIMS = {                     # M4/M7 are global-dynamic; M8: ≥1 pipeline per kind
    "scorer":  {1, 2, 3, 5, 6},
    "judge":   {1, 2, 3, 6},          # M5 excluded: verdict determinism is the provider's
    "dataset": {1, 2, 3, 6},          #   property, not the wrapper's
    "target":  {1, 2, 3, 6},          # M6 required: the model target is the kind's
    "sink":    {1, 2, 6},             #   riskiest error surface
}                                     # sink M2 = empty-run emit; M6 = degrade/error path;
                                      # sink M3/M5 are extra rows where an artifact exists
EXTRA_SUITES = {"gating": {1, 2, 6}, "engine": {8}}   # non-registry rows, same enforcement
WAIVED = {("target", "echo", 6): "no failure modes by design"}
```

1. **The component census is derived**, from a fresh-subprocess probe of the live registries
   (kinds discovered dynamically), never from a list in the test file. A new registry kind is
   censused automatically and fails until the policy carries a row for it.
2. **Declarations are literal but checked.** Matrix classes carry literal
   `MATRIX_KIND`/`MATRIX_COMPONENTS` attributes. The principle: *a literal is banned where it
   claims completeness unchecked (the old M7 lists); a literal cross-checked against the live
   census is a checked declaration.* Both directions are enforced — an undeclared registered
   component fails, and a declared-but-unregistered component fails.
3. **Floors are minimums, waivers are data.** A dim is floor for a kind iff it is meaningful
   for every member absent a documented waiver, and waivers stay a small minority;
   subset-meaningful dims are extra rows, welcome but not required. Waiver hygiene is
   self-guarded both ways (stale waiver fails; satisfied waiver fails).
4. **Alias pairings are frozen by exact equality** per kind (`FROZEN_ALIAS_MAP`) — the
   registry's alias table has no duplicate guard, so a silently repointed alias must be a CI
   failure, not a diff a reviewer might notice.
5. **The artifact is generated.** `docs/matrix-coverage.md` renders the grid (per-cell static
   test counts), waived cells with reasons, the alias tables, and the recorded follow-on
   obligations (`FOLLOW_ON`, with satisfied-row hygiene) — regenerated via
   `python tests/test_matrix_coverage.py --update`, freshness-gated by the root suite.
6. **Scope boundary.** The matrix covers the root harness registries plus the gating/engine
   extra suites; `extend-matrix-to-fleet` extends the same convention to the five sibling
   packages (per-package floors keyed by package in the same policy module) and the skills
   layer. `experiments/backend-validation` (temporary, own gate, outside `make check-all`),
   `demo/`, and `examples/` are out of scope.

## Consequences

- **Positive.** "Is the matrix complete" becomes a CI answer, not an audit finding. The next
  registered component — including `add-stateful-outcome-evaluation`'s `STATE_ADAPTERS` —
  cannot land rowless without a red gate naming exactly what is missing.
- **Positive.** The dangling F-045 claim ("captured … into `eval_test_matrix.xlsx`", a file
  never committed) is replaced by an artifact that cannot drift from reality.
- **Negative.** The class-attr and method-name conventions are load-bearing: a refactor that
  renames `test_m2_…` methods or drops the attributes moves cells out of the census. The
  extractor's vacuity self-tests (fail on zero classes/cells) bound this, but the convention
  must be kept.
- **Negative.** Per-kind floors are policy, and policy invites relitigating. The floor-vs-
  extra rule above is the tiebreaker; changes to `REQUIRED_DIMS` amend this ADR.
- **Neutral.** No production code is touched; the matrix suite grows in `tests/`, which is
  exempt from the file-length gate and outside the coverage measurement source.

## Compliance

Enforced by `tests/test_matrix_coverage.py` (policy floors, both-directions census check,
waiver/obligation hygiene, alias freeze, doc freshness) running in the root suite on all three
Pythons; by `scripts/validations/F_053.py` (which imports the extractor and policy from
`tests/_matrix_coverage.py` rather than restating them — the F-052 no-restatement principle);
and by `eval-harness-ci.yml`'s path filters including the generated document, so a hand edit
to it re-runs the freshness gate.

# Change: add-eval-matrix-completeness

**Status:** implemented · **Date:** 2026-08-08 · **Author track:** `claude/` agent lane
**Motivated by:** `./review.md` (peer review of the matrix-completion plan: every citation
re-derived against the tree, plus an adversarial design pass)
**Compiles down to:** an F-ID claimed at land + [ADR 0032](../../../../docs/decisions/0032-matrix-completeness-policy.md)

## Why

`tests/test_matrix_eval_tools.py` is the declared test matrix — "All eval tools ×
standardized metrics" (its own docstring), the offline-DI reference `AGENTS.md` names — and it
is silently incomplete in three compounding ways:

- **Seven registered scorers have zero matrix rows.** F-051's trajectory scorers
  (`src/eval_harness/scorers/trajectory.py:189-390`) registered after the matrix was written;
  only the dynamically-parametrized M4 class picks them up. M1/M2/M3/M5/M6/M7/M8 rows do not
  exist.
- **`TestM7Registry` is hand-maintained lists** (`tests/test_matrix_eval_tools.py:75-126`),
  already stale by those seven scorers, and 13 of the 23 registered aliases are asserted
  nowhere. This is the same manual-list-vs-derived-reality defect class F-050 (skills CI
  coverage) and F-052 (guard reachability) closed elsewhere.
- **Nothing enforces completeness.** A component registered tomorrow (the queued
  `STATE_ADAPTERS` registry, for instance) lands with no matrix rows and CI stays green. A
  one-shot backfill would go stale the moment the next change lands.

Two shipped defects surfaced while verifying this proposal, both fixed by it:

1. `config/trajectory_eval.yaml` **fails its own gate today** — `trajectory_in_order`
   pass_rate 0.0 against a min of 0.9, because its reference arguments never matched what
   `tests/_sut.py:trajectory_demo` emits, and the covering test only asserts non-emptiness.
2. `.github/workflows/quality-gates.yml` carries a **dead `--cov=F_052`** — the module is
   imported by nothing in that step's file list, so coverage warns "never imported" and the
   entry measures nothing.

Also corrected: the `NEXT_STEPS.md` F-045 entry claims the matrices were "captured into
`eval_test_matrix.xlsx`" — that file was never committed on any ref. The canonical artifact
this change creates (`docs/matrix-coverage.md`, generated and freshness-gated) replaces the
dangling claim.

## What changes

- Matrix rows for all 7 trajectory scorers (M1–M8, including an engine pipeline over the
  shipped `tests._sut:trajectory_demo` callable target).
- Sparse cells filled to a per-kind floor (`REQUIRED_DIMS`, ADR 0032), with an explicit
  reviewable waiver map for cells that are waived rather than missing.
- `TestM7Registry` rewritten to derive from `tests/plugin_registry_baseline.json` + the live
  registries (resolvability), plus a per-kind **exact-equality alias→canonical map assertion**
  (the directed pairing guarantee the deleted hardcoded pairs carried — `Registry._aliases`
  assignment is unguarded, so a silently repointed alias must fail CI, not a doc diff).
- A **matrix completeness guard**: `tests/test_matrix_coverage.py` +
  `tests/_matrix_coverage.py` — fresh-subprocess registry census (kinds discovered
  dynamically; a future sixth registry is censused automatically), AST cell map over
  `tests/test_matrix_*.py`, per-kind policy floors, both-directions failure (unmapped matrix
  class; registered component with no rows).
- A **generated committed artifact**, `docs/matrix-coverage.md`, with a `--check` freshness
  gate run inside the root suite (the `mermaid_gen.py --check` contract).
- The two shipped-defect fixes above, and the `NEXT_STEPS.md` correction.

## Scope / non-goals

- **Non-goal: any new evaluation capability.** No production code changes;
  `src/**` is untouched (`scorers/trajectory.py` sits at 455 of the 500-line ceiling and
  gains nothing here). The queued OpenSpec changes are not implemented; their matrix
  obligations are recorded as data (`FOLLOW_ON`) rendered in the artifact with
  stale-row hygiene.
- **Non-goal: sibling-package matrices.** `extend-matrix-to-fleet` (the follow-on change)
  carries the five bespoke package suites and the skills-layer floors.
- **Non-goal: benchmark adapters and retrieval precision/recall scorers.** The former needs
  its own charter-scope decision (`docs/plans/agent-eval-coverage/REVIEW.md`), the latter has
  no scope decision recorded yet; both stay out.

## Impact

- **Protected paths:** `tests/**`, `config/**`, `features.yaml`, `scripts/validations/**`,
  `.github/**` — effectively the whole implementation. Per the PR #82 shape recorded in
  `add-measurement-harness-wedge/tasks.md`, this lands as ONE `eval-change-approved`-labelled
  PR with protected changes isolated into their own commits (strict per-PR isolation would
  strand test-only commits below coverage floors).
- **No `SCHEMA_VERSION` change, no baseline regens** — zero `src/**` surface changes; both
  baseline `--update` runs are verified no-ops.
- Coverage floors unchanged: root `eval_harness` 96, `scripts/` 85.

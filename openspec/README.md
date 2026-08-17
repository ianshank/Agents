# openspec/ — spec-driven change coordination (reversible spike)

This directory is a **thin coordination/authoring front-end** trialled over the repo's
existing, CI-enforced spec system. It is **not** a source of truth and is fully removable
(see [`../docs/openspec-spike.md`](../docs/openspec-spike.md)). Capability state stays
single-sourced in `features.yaml`; decisions in `docs/decisions/`; roadmaps in `docs/plans/`.

## Layout

| Path | Purpose |
|---|---|
| `project.md` | Pointers to the authoritative system; conventions this layer must respect |
| `AGENTS.md` | Fleet-coordination contract — which agent/sub-agent owns each lifecycle phase |
| `changes/<id>/` | An in-flight change: `proposal.md`, `design.md`, `tasks.md`, `review.md`, `specs/<cap>/spec.md` deltas |
| `changes/archive/` | Landed changes (created on first archive) |

## How a change maps to the enforced back-end

`proposal.md`+`tasks.md` → `docs/plans/<topic>/PLAN.md` · `design.md` → a numbered ADR ·
`specs/<cap>/spec.md` deltas → `features.yaml` F-IDs + `scripts/validations/F_0NN.py` proofs ·
`review.md` → the house `REVIEW.md` idiom · `openspec archive` → `status: done` +
`implemented_in:<sha>`. `openspec/specs/` is intentionally not populated (no duplicate
registry).

## Current changes

Every directory under `changes/` (excluding `changes/archive/`) must appear here, and no
archived one may — asserted by the *OpenSpec change index* guard in
[`.github/workflows/docs.yml`](../.github/workflows/docs.yml). This section listed 2 of 9
before that guard existed.

- [`changes/add-eval-matrix-completeness/`](changes/add-eval-matrix-completeness/) —
  *proposed.* The declared test matrix ("all eval tools × standardized metrics") is silently
  incomplete — seven registered scorers have zero rows, the M7 lists are hand-maintained and
  stale, and nothing enforces completeness. Derives the component census from the live
  registries, sets per-kind dimension floors with reviewable waivers (ADR 0032), freezes the
  alias→canonical pairings, and generates a freshness-gated `docs/matrix-coverage.md`.
- [`changes/add-measurement-harness-wedge/`](changes/add-measurement-harness-wedge/) —
  *proposed.* The system has strong internal validation and no external evidence. Replaces the
  rejected "add-business-readiness-wedge" (which would have pulled a public
  `merge_gate_report` CLI into the harness) with a measurement wedge that does not widen the
  public surface.
- [`changes/extend-judge-calibration/`](changes/extend-judge-calibration/) — *proposed.*
  Answers the external analysis's "judge calibration: Not Covered" grade, which is refuted —
  Cohen's κ with a statistical-power floor already ships — and scopes what is genuinely
  missing on top of it.
- [`changes/add-panel-judge/`](changes/add-panel-judge/) — *proposed.* A `panel` judge: one
  registered component fanning an evaluation out to N member judges and aggregating under an
  explicit strategy, surfacing disagreement instead of averaging it away and abstaining
  rather than guessing. Specifies per-member budget accounting (a naive panel under-charges
  `judge_budget` by factor N) and the calibration obligations — panel κ, pairwise member
  redundancy κ, named-artifact gating — that keep a council advisory until it earns trust.
  Aligned with `extend-judge-calibration`.
- [`changes/add-repeat-reliability-metrics/`](changes/add-repeat-reliability-metrics/) —
  *proposed.* `pass^k` over k independent attempts per item. Depends on
  `add-agent-trajectory-evaluation` (landed); authorised by ADR 0031.
- [`changes/add-stateful-outcome-evaluation/`](changes/add-stateful-outcome-evaluation/) —
  *proposed.* Evaluating end-state rather than final text. Depends on
  `add-repeat-reliability-metrics`, which defines per-attempt reset/isolation.
- [`changes/add-production-eval-flywheel/`](changes/add-production-eval-flywheel/) —
  **blocked.** Ingesting production traces back into the golden dataset. Blocked on a
  CHARTER §3 ratified amendment plus its own ADR — §3 lists "a general observability
  platform" as a non-goal — and on the three changes above.
- [`changes/harden-quality-gate-integrity/`](changes/harden-quality-gate-integrity/) —
  *proposed.* The generated `quality-gate.sh` coverage gate could be made to report green
  without meeting its real threshold: `COV_FAIL_UNDER` and single-source `COVERAGE_SOURCE`
  were live, unguarded environment overrides, `PYTEST_ADDOPTS` passed through to pytest
  unguarded, and four packages' coverage-exclude regex was unanchored (excluding any line
  containing `...`, not just a standalone stub body) despite ADR 0009 claiming it was aligned
  with root's already-anchored pattern. All four are closed with generation-time literals, an
  active `PYTEST_ADDOPTS` guard, an anchored regex verified safe against each package's real
  coverage suite, and positive-control tests that run the real gate against a real
  under-covered fixture.

## Archived changes

Landed; kept for provenance. Each carries its F-ID and the commit it landed in.

| Change | F-ID | Landed in |
|---|---|---|
| [`changes/archive/eval-proxy-and-estimator/`](changes/archive/eval-proxy-and-estimator/) | F-047 | `5404912bdb` |
| [`changes/archive/merge-gate-health-integrity/`](changes/archive/merge-gate-health-integrity/) | F-049 | `8f7affd6c0` |
| [`changes/archive/skills-ci-coverage-floor/`](changes/archive/skills-ci-coverage-floor/) | F-050 | `c5e7227c6a` |
| [`changes/archive/add-agent-trajectory-evaluation/`](changes/archive/add-agent-trajectory-evaluation/) | F-051 | `a5e1a7847f` |

## Removing this spike

`rm -rf openspec/ docs/openspec-spike.md`, then drop the six navigation references added
with it — the `mkdocs.yml` nav entry, **both** `docs/README.md` entries (the `../openspec/`
row under "Change proposals" and the spike bullet under "Spikes"), the `openspec/` row in
`AGENTS.md`'s documentation map, the `openspec/` block in the root `README.md` Layout tree,
and the `.dockerignore` line. Deleting the
directory alone leaves `mkdocs.yml` pointing at a missing page — a dangling-nav warning
today (the docs build is deliberately non-strict), and a hard failure under `--strict`.

Verify with `python scripts/validate.py --tier fast` and a `mkdocs build` that emits no
*openspec* nav warning (the tree already carries ~50 unrelated pre-existing warnings, so a
zero total is the wrong bar — grep the output instead); no
code, CI job, or F-ID validation depends on this directory. Full procedure in
[`../docs/openspec-spike.md`](../docs/openspec-spike.md).

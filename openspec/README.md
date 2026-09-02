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

- [`changes/prove-m8-execution/`](changes/prove-m8-execution/) — *proposed.* The M8
  (Composability) matrix dimension credits a component for appearing in a validated pipeline
  config, not for executing — one credited cell is provably invoked zero times. Replaces
  config-presence credit with an execution ledger, adds the two network judges' missing
  `client=` seams, and widens M8 honestly across the 41 registered components once the
  mechanism means something. Motivated by `docs/plans/eval-evidence-integrity/REVIEW.md`.
- [`changes/add-measurement-harness-wedge/`](changes/add-measurement-harness-wedge/) —
  *proposed.* The system has strong internal validation and no external evidence. Replaces the
  rejected "add-business-readiness-wedge" (which would have pulled a public
  `merge_gate_report` CLI into the harness) with a measurement wedge that does not widen the
  public surface.
- [`changes/extend-judge-calibration/`](changes/extend-judge-calibration/) — *implemented,
  pending archive.* Answers the external analysis's "judge calibration: Not Covered" grade,
  which is refuted — Cohen's κ with a statistical-power floor already ships — and scopes what
  is genuinely missing on top of it. Claims F-057.
- [`changes/add-repeat-reliability-metrics/`](changes/add-repeat-reliability-metrics/) —
  *implemented, pending archive.* `pass^k` over k independent attempts per item. Depends on
  `add-agent-trajectory-evaluation` (landed); authorised by ADR 0031. Claims F-056.
- [`changes/add-production-eval-flywheel/`](changes/add-production-eval-flywheel/) —
  **blocked.** Ingesting production traces back into the golden dataset. Blocked on a
  CHARTER §3 ratified amendment plus its own ADR — §3 lists "a general observability
  platform" as a non-goal — and on the three changes above.

## Archived changes

Landed; kept for provenance. Each carries its F-ID and the commit it landed in.

| Change | F-ID | Landed in |
|---|---|---|
| [`changes/archive/eval-proxy-and-estimator/`](changes/archive/eval-proxy-and-estimator/) | F-047 | `5404912bdb` |
| [`changes/archive/merge-gate-health-integrity/`](changes/archive/merge-gate-health-integrity/) | F-049 | `8f7affd6c0` |
| [`changes/archive/skills-ci-coverage-floor/`](changes/archive/skills-ci-coverage-floor/) | F-050 | `c5e7227c6a` |
| [`changes/archive/add-agent-trajectory-evaluation/`](changes/archive/add-agent-trajectory-evaluation/) | F-051 | `a5e1a7847f` |
| [`changes/archive/add-eval-matrix-completeness/`](changes/archive/add-eval-matrix-completeness/) | F-053 | `bc0ae2c494` |
| [`changes/archive/harden-quality-gate-integrity/`](changes/archive/harden-quality-gate-integrity/) | F-054 | `711564123e` |
| [`changes/archive/pin-lockstep-tool-versions/`](changes/archive/pin-lockstep-tool-versions/) | F-055 | `86eeb5cf1d` |
| [`changes/archive/test-skill-validator-library/`](changes/archive/test-skill-validator-library/) | — | `8a8e25c` |
| [`changes/archive/add-openspec-implementation-review/`](changes/archive/add-openspec-implementation-review/) | — | `3f6bd6c` |
| [`changes/archive/add-foundation-reviewer-charters/`](changes/archive/add-foundation-reviewer-charters/) | — | `537d1f2` |
| [`changes/archive/add-panel-judge/`](changes/archive/add-panel-judge/) | F-059 | `955bc9c919` |
| [`changes/archive/add-stateful-outcome-evaluation/`](changes/archive/add-stateful-outcome-evaluation/) | F-060 | `b709ae1903` |

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

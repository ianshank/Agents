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

- [`changes/add-agent-in-the-loop-testgen/`](changes/add-agent-in-the-loop-testgen/) —
  *in implementation.* Owner defaults recorded 2026-09-06 in `OWNER_DEFAULTS.md`
  (option (a) sequential pipeline). F-ID claimed at land.
- [`changes/add-measurement-harness-wedge/`](changes/add-measurement-harness-wedge/) —
  *partially implemented.* **WS-0 (the blocking hygiene gate) landed as F-048** — credential scrub,
  `.gitleaks.toml`, and the fail-closed secret scan at `quality-gates.yml`. WS-0 tasks 0.5–0.7
  are done in the checkbox ledger; H.1 (rotation confirmation) remains human. WS-1 through WS-5
  stay open. House docs disagree on whether WS-1 needs a CHARTER §3 amendment — recorded in
  [`docs/plans/vp-strategic-deep-dive/DECISIONS.md`](../docs/plans/vp-strategic-deep-dive/DECISIONS.md)
  §5; do not implement WS-1 until that is decided. Replaces the rejected
  "add-business-readiness-wedge" (which would have pulled a public `merge_gate_report` CLI into
  the harness) with a measurement wedge that does not widen the public surface.
- [`changes/add-production-eval-flywheel/`](changes/add-production-eval-flywheel/) —
  **blocked.** Ingesting production traces back into the golden dataset. Blocked on a
  CHARTER §3 ratified amendment plus its own ADR — §3 lists "a general observability
  platform" as a non-goal. Calibration packages it originally queued behind are archived;
  remaining in-flight dependency is add-measurement-harness-wedge.

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
| [`changes/archive/add-repeat-reliability-metrics/`](changes/archive/add-repeat-reliability-metrics/) | F-056 | `c77aade048` |
| [`changes/archive/extend-judge-calibration/`](changes/archive/extend-judge-calibration/) | F-057 | `1cfc342f7a` |
| [`changes/archive/test-skill-validator-library/`](changes/archive/test-skill-validator-library/) | — | `8a8e25c` |
| [`changes/archive/add-openspec-implementation-review/`](changes/archive/add-openspec-implementation-review/) | — | `3f6bd6c` |
| [`changes/archive/add-foundation-reviewer-charters/`](changes/archive/add-foundation-reviewer-charters/) | — | `537d1f2` |
| [`changes/archive/add-panel-judge/`](changes/archive/add-panel-judge/) | F-059 | `955bc9c919` |
| [`changes/archive/add-stateful-outcome-evaluation/`](changes/archive/add-stateful-outcome-evaluation/) | F-060 | `b709ae1903` |
| [`changes/archive/add-gate-decision-provenance/`](changes/archive/add-gate-decision-provenance/) | F-062 | `14b0101dfb` |
| [`changes/archive/prove-m8-execution/`](changes/archive/prove-m8-execution/) | F-063 | `7800a3fec5` |
| [`changes/archive/add-testgen-eval-matrix/`](changes/archive/add-testgen-eval-matrix/) | F-065 | `d0c761d25b` |
| [`changes/archive/add-rca-eval-matrix/`](changes/archive/add-rca-eval-matrix/) | F-067 | `d75028c62c1f` |
| [`changes/archive/add-requirements-gen-eval-matrix/`](changes/archive/add-requirements-gen-eval-matrix/) | F-068 | `49c7db829066` |

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

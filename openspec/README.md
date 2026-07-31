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

- [`changes/eval-proxy-and-estimator/`](changes/eval-proxy-and-estimator/) — proxy-correlation
  measurement, audit-selection-propensity logging, and a dual `wilson`/`ppi++` report
  estimator, from the 2026-07-25 peer review of the "swap Wilson → PPI++" critique. Gate
  untouched.
- [`changes/skills-ci-coverage-floor/`](changes/skills-ci-coverage-floor/) — closes a
  reproducible CI gap where 4 of 11 registered skills ran no CI on their own changes
  (including the vendored-script drift guard); adds an `all-skills` structural/registry/drift
  job and a registration + job-coverage guard, from a 2026-07-31 ROI review of `skills/` CI
  coverage. See ADR 0030.

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

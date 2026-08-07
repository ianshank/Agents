# OpenSpec adoption — reversible spike

**Status:** spike (reversible-adoption pattern, per `docs/phoenix-spike.md`).
**Date:** 2026-07-25.
**Related:** `openspec/project.md`, `openspec/AGENTS.md`,
`openspec/changes/archive/eval-proxy-and-estimator/`, `docs/plans/agent-record-decontamination/PLAN.md:171`.

## What this is

A trial of [OpenSpec](https://github.com/Fission-AI/OpenSpec) as a **coordination/authoring
front-end** over the repo's existing, CI-enforced spec system — *not* a replacement for it.
It is introduced exactly the way the Phoenix integration was: additive, off to the side, and
removable without trace.

## Why a spike, not adoption

- A SpecKit-vs-OpenSpec bake-off was previously **dropped**
  (`docs/plans/agent-record-decontamination/PLAN.md:171`). This spike revisits OpenSpec only
  as a thin front-end, so the earlier "nothing to be unchanged relative to" objection no
  longer applies — the enforced back-end remains the source of truth.
- The home-grown system (`features.yaml` + `scripts/validations/F_*.py` + `validate.py` +
  ADRs) is **stricter** than OpenSpec's markdown specs, because its acceptance criteria
  execute in CI. OpenSpec adds authoring ergonomics and a fleet-coordination vocabulary; it
  must never become a second, weaker registry.

## Scope of the spike

The single change `openspec/changes/archive/eval-proxy-and-estimator/` (the PPI++/proxy work from
the 2026-07-25 peer review). Its artifacts map down as:

- `proposal.md` + `tasks.md` → `docs/plans/<topic>/PLAN.md`
- `design.md` → a numbered ADR
- `specs/<cap>/spec.md` deltas → `features.yaml` F-IDs + `scripts/validations/F_0NN.py`
- `review.md` → the house `REVIEW.md` idiom

`openspec/specs/` is deliberately **not** populated — capability state stays single-sourced
in `features.yaml`.

## Reversibility contract

The spike is load-bearing for nothing — but it *is* referenced from the navigation
surfaces, so deleting only the directory leaves `mkdocs.yml` pointing at a page that no
longer exists. Measured: the build still exits 0 (this repo runs mkdocs **non-strict** by
design, see the note in `mkdocs.yml`) but emits

> `WARNING - A reference to 'openspec-spike.md' is included in the 'nav' configuration,
> which is not found in the documentation files.`

which becomes a hard failure the day `--strict` is adopted. Remove the references too:

```bash
rm -rf openspec/ docs/openspec-spike.md
# Drop the six references added alongside it, or the nav is left dangling:
#   mkdocs.yml        nav -> "OpenSpec coordination layer: openspec-spike.md"
#   docs/README.md    BOTH: the `../openspec/` entry under "Change proposals"
#                     AND the openspec-spike bullet under "Spikes"
#   AGENTS.md         the `openspec/` row in the root documentation map
#   README.md         the `openspec/` block in the repository Layout tree
#   .dockerignore     the `openspec/` line under "Docs (not needed in container)"

python scripts/validate.py --tier fast   # still green — no F-proof depends on openspec/
make check-all                            # unaffected

# The removal is clean when mkdocs emits NO openspec nav warning. Do not check for a
# zero total: the tree already carries ~50 pre-existing warnings (docs/ pages linking to
# repo-root files that are not part of the site), so a raw count proves nothing here.
mkdocs build 2>&1 | grep -i openspec       # expect no WARNING line (INFO is fine)
```

No code imports `openspec/`; no CI job reads it; no F-ID validation references it. The only
coupling is documentation navigation, which the six references above cover.

## Evaluate-and-decide criteria

After the `eval-proxy-and-estimator` change lands via this front-end, decide (record as an
ADR): did the OpenSpec vocabulary reduce coordination overhead across the fleet enough to
justify keeping it, versus authoring `docs/plans/<topic>/` directly? If not, delete per the
contract above. If yes, add a `make`/CI convenience that checks each `specs/<cap>/spec.md`
delta has a matching `features.yaml` F-ID before archive (the only automation worth adding —
and even that stays advisory).

**Trigger status (2026-08-06): fired, decision outstanding.** `eval-proxy-and-estimator`
landed as F-047 (`5404912bdb`) and three further changes have landed since — F-049, F-050,
F-051 — all four now under `openspec/changes/archive/`. So the evaluate-and-decide condition
above is met and the keep-or-delete ADR has not been written. That call is a human one and is
deliberately **not** made here.

What the interval did surface, recorded so the eventual ADR argues from evidence rather than
impression: the layer's failure mode is silent staleness. Four changes stayed marked
`proposed` after landing, `README.md`'s index listed 2 of 9, and nothing detected either —
because nothing executes. That is the predicted "second, weaker registry" risk above,
observed. It is now mechanically checked by the *OpenSpec change index* guard in
`.github/workflows/docs.yml`, which is the advisory automation this section anticipated,
one step earlier in the lifecycle than proposed (index completeness, not F-ID matching).

# OpenSpec adoption — reversible spike

**Status:** spike (reversible-adoption pattern, per `docs/phoenix-spike.md`).
**Date:** 2026-07-25.
**Related:** `openspec/project.md`, `openspec/AGENTS.md`,
`openspec/changes/eval-proxy-and-estimator/`, `docs/plans/agent-record-decontamination/PLAN.md:171`.

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

The single change `openspec/changes/eval-proxy-and-estimator/` (the PPI++/proxy work from
the 2026-07-25 peer review). Its artifacts map down as:

- `proposal.md` + `tasks.md` → `docs/plans/<topic>/PLAN.md`
- `design.md` → a numbered ADR
- `specs/<cap>/spec.md` deltas → `features.yaml` F-IDs + `scripts/validations/F_0NN.py`
- `review.md` → the house `REVIEW.md` idiom

`openspec/specs/` is deliberately **not** populated — capability state stays single-sourced
in `features.yaml`.

## Reversibility contract

The spike is load-bearing for nothing. To remove it:

```bash
rm -rf openspec/ docs/openspec-spike.md
python scripts/validate.py --tier fast   # still green — no F-proof depends on openspec/
make check-all                            # unaffected
```

No code imports `openspec/`; no CI job reads it; no F-ID validation references it.

## Evaluate-and-decide criteria

After the `eval-proxy-and-estimator` change lands via this front-end, decide (record as an
ADR): did the OpenSpec vocabulary reduce coordination overhead across the fleet enough to
justify keeping it, versus authoring `docs/plans/<topic>/` directly? If not, delete per the
contract above. If yes, add a `make`/CI convenience that checks each `specs/<cap>/spec.md`
delta has a matching `features.yaml` F-ID before archive (the only automation worth adding —
and even that stays advisory).

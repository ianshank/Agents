# OpenSpec — project context

OpenSpec is used here as a **thin coordination/authoring layer**, not a source of truth.
The authoritative, CI-enforced spec system is unchanged and lives where it always has:

- **Capability registry:** `features.yaml` (F-IDs) validated by `features.schema.json`.
- **Executable proofs:** `scripts/validations/F_*.py`, aggregated by `scripts/validate.py`
  (schema + `depends_on` DAG + git-provenance + tier-matched proofs), run in CI by
  `.github/workflows/quality-gates.yml`.
- **Decisions:** immutable ADRs under `docs/decisions/NNNN-*.md`.
- **Roadmaps:** `docs/plans/<topic>/{PLAN.md,REVIEW.md}`.
- **North star / invariants:** `docs/CHARTER.md`; agent constraints in `AGENTS.md`; the
  harness spec in `HARNESS_SPEC.md`.

Read those first. This directory never restates them; it only coordinates in-flight change
proposals and maps them onto the artifacts above (see `AGENTS.md` in this directory).

## Why OpenSpec is a front-end here (not a migration)

A SpecKit-vs-OpenSpec bake-off was previously evaluated and **dropped**
(`docs/plans/agent-record-decontamination/PLAN.md:171`). The repo's home-grown system is
stricter than OpenSpec's markdown specs (its proofs execute in CI), so OpenSpec is added
only as an authoring convenience and a fleet-coordination surface. It is reversible:
deleting `openspec/` leaves the enforced system fully intact (see `docs/openspec-spike.md`).

## Conventions this layer must respect

- **Protected paths** need the `eval-change-approved` label + CODEOWNERS review:
  `features.yaml`, `features.schema.json`, `scripts/validations/**`, `.github/**`,
  root `tests/**`, `config/**`, `src/eval_harness/{gating,scorers,judges}/`
  (authoritative list: `scripts/eval_protected_paths.py`).
- **No numeric literals at call sites** — tunables live on frozen `*Config` dataclass
  fields (`AGENTS.md`).
- **F-numbers are claimed at land, never reserved** in a proposal.
- **`agent_core` is config-file-free** — calibration math takes no YAML knobs.

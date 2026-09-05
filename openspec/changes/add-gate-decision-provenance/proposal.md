# Change: add-gate-decision-provenance

**Status:** proposed · **Date:** 2026-09-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/scenario-eval-matrices/REVIEW.md` §A6 (as corrected in Part E)
**Compiles down to:** `docs/plans/scenario-eval-matrices/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

**The quality gate's decision is never recorded anywhere.**

`EvalEngine.run()` builds the `RunResult`, emits it to every sink, and returns
(`engine.py:405-413`). Only afterwards, in the CLI, does `evaluate_gate(config.gate, run)` run —
purely to choose an exit code (`cli.py:92-99`). `RunResult` carries no gate field and `to_dict()`
emits none (`core/types.py:176-196`).

Three consequences, in ascending order of how much they matter:

1. **Every sink is blind to the gate.** The `html_file` artifact, the Langfuse/Phoenix/BrainTrust
   exports, the JSON payload — none of them can say whether the run passed, which rule failed, or
   by how much. A run's own record does not contain its verdict.
2. **A soak cannot be diffed.** "Run this non-blocking for two weeks and see what it would have
   done" requires the decisions to exist as data. Today they exist as two lines of CI stdout, and
   comparing them across runs means scraping logs.
3. **The claim the gates protect is unevidenced.** "These metrics cannot be quietly weakened" rests
   on protected paths and CODEOWNERS, which is true — but there is no artifact showing what the
   gate actually decided on any given run, so the claim cannot be *demonstrated*, only asserted.

Separately, and more narrowly: a gate rule today either blocks or does not exist. A scorer whose
threshold nobody has calibrated has no home. That is the problem the source plan tried to solve
with "report-only mode", and it is real — but it is the second-order problem. The first is that
even a blocking decision leaves no trace.

## What changes

**1. The gate decision becomes part of the run record.**
`RunResult` gains an optional `gate` field, populated before sinks fire, carrying the verdict, each
evaluated rule, its observed value, and its bound. Omitted from the payload when no gate is
configured, so pre-change output stays byte-identical.

**2. A gate rule can be declared advisory.**
`GateRule` gains `report_only: bool = False`. An advisory rule is evaluated on the same path and
filed to an advisory channel instead of the failure list.

## Why per-rule advisory, when whole-gate neutralization already exists

The cheaper alternative is real and should be stated: `evaluate_gate` is a pure function called
from exactly one site, and the exit code is decided in the CLI. A CI job can therefore run
`eval-harness run` non-blocking and map its exit code to success — which is precisely what the
repository's own shadow merge-gate does (`calibrated-merge-gate.yml:69-73`: "all three decision
exit codes … map to job success; only internal/usage errors fail"). That pattern needs no code
change at all.

It is not sufficient here, for one reason: **it is all-or-nothing.** Neutralizing the exit code
makes *every* rule advisory, including the calibrated ones that should still block. A soak on four
new scorers would silently disarm the thresholds the repository already trusts, for the entire
duration of the soak. Per-rule granularity is the whole point — new rules advisory, existing rules
blocking, in the same run.

The workflow pattern remains the right tool for soaking an entire gate. This change is for soaking
one rule inside a gate that is otherwise live.

## Scope / non-goals

- **Non-goal: a second gate system.** One evaluation path. `report_only` changes where a verdict is
  filed, never how it is computed.
- **Non-goal: a CLI flag.** `report_only` lives in `config/` — a protected path — so promotion or
  demotion of a rule is a reviewed act with a diff. A flag would let a red gate be silenced at the
  call site with nothing in the repository recording it, which is the failure
  `coverage-floors.yaml` exists to close.
- **Non-goal: auto-promotion.** Deciding when an advisory rule has earned a blocking threshold is a
  human judgement backed by evidence, not a mechanism.

## Authority — this needs its own ADR, and does not have one yet

CHARTER §4 invariant 1 holds the engine, core models and registries unmodified when a capability is
added through a registry. ADR 0031 carves a narrow exception for agent evaluation — trajectory,
repeated-run reliability, environment state — under written compatibility obligations.

**A gate field on `RunResult` is not within that grant.** It is an additive core-model and engine
change for a different purpose, so it needs its own ADR under the same obligations ADR 0031
established: append-only fields, defaults reproducing current behaviour, no freezing, `SCHEMA_VERSION`
untouched, surface baselines regenerated. The ADR is written at land (next free number 0042);
naming the requirement here rather than proceeding on ADR 0031's authority is the point — the
flywheel proposal's "ADR 0031 … does **not** authorise this. Do not begin implementation on the
strength of it" is the precedent for saying so out loud.

## Impact

- **Protected paths:** `src/eval_harness/gating/**`, `config/**`, `features.yaml`,
  `scripts/validations/**`, root `tests/**`. Needs `eval-change-approved` + CODEOWNERS review.
- Root `eval_harness` coverage floor **96%**.
- `tests/public_surface_baseline.json` regeneration (F-039 exact-equality freeze).
- `SCHEMA_VERSION` untouched: both fields optional with defaults reproducing current behaviour.
- No new matrix components — `gating` is not a `MATRIX_KIND`. Confirm against
  `tests/_matrix_coverage.py` rather than assuming (task 4.1).

## Why this lands first

`add-testgen-eval-matrix`, `add-rca-eval-matrix` and `add-requirements-gen-eval-matrix` each
introduce scorers with uncalibrated thresholds, and all three want their soak evidence in the run
artifact rather than in CI logs. This change is the smallest of the four, has no corpus work, and
is the cheapest way to prove the protected-path review loop before larger changes queue behind it.

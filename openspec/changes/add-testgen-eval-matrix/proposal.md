# Change: add-testgen-eval-matrix

**Status:** proposed · **Date:** 2026-09-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/scenario-eval-matrices/REVIEW.md` (peer review of an externally
supplied four-package plan)
**Depends on:** `add-gate-decision-provenance` (a new scorer has no calibrated threshold on day one),
`prove-m8-execution` (see "Why the ordering matters")
**Compiles down to:** `docs/plans/scenario-eval-matrices/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

The harness scores an agent's *answer* and its *path* (F-051 trajectory scorers) and its *effect on
the world* (F-060 state adapters). It has nothing that scores an agent's **test suite**, which is
the artifact this organisation's agents most often produce. `pass^k` and `ReliabilityAggregator`
(F-056) exist and have no test-generation signal to aggregate.

The gap is narrower than "we need test-generation evaluation", and naming it narrowly is what keeps
this change small. Three things are missing:

1. An **execution seam** — nothing runs a generated suite and reports what happened.
2. **Deterministic scorers** over that evidence — does the suite run, does it kill seeded mutants,
   does it stay green on correct code, does it cover the stated obligations.
3. A **corpus** with known-good and known-bad reference cases.

Everything else the source plan proposed — coverage delta, revision rate, duplicate rate,
traceability, boundary/negative-path partitions, unsupported-assumption detection — is real work
and is deferred. Four scorers that are trusted beat fourteen that are not.

## What changes

- A new **callable target** that executes a generated suite in a sandbox and returns structured
  evidence on `TargetOutput.metadata`. It is added to `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST`
  explicitly (ADR 0039 — the allowlist is deny-by-default).
- Four scorers, all **pure readers** of that evidence:
  `test_executability`, `testgen_mutation_score`, `testgen_green_on_correct`,
  `requirement_obligation_recall`.
- A synthetic focal-method corpus with seeded mutants at `corpora/testgen/v1/`.
- Matrix rows for all four scorers, and the regenerated `docs/matrix-coverage.md`.
- One advisory (`report_only`) gate rule per scorer. No blocking threshold ships in this change.

## Scope / non-goals

- **Non-goal: `testgen_flake_rate` as a scorer.** A `Scorer` receives one `(item, output)` pair
  (`src/eval_harness/core/interfaces.py:39-49`) and cannot re-execute a target. Flakiness is already expressible:
  `repetitions: 5` on `RunSettings` plus `metric: pass_power_k` on `test_executability` (F-056).
  Registering a scorer for it would duplicate shipped machinery and owe five unnecessary matrix
  cells.
- **Non-goal: real internal code as corpus material.** The corpus is synthetic and generated. See
  "Why the corpus is synthetic".
- **Non-goal: a judge.** Every scorer here is decidable by execution. Nothing in this change calls
  a judge, so `require_calibration_for_judge_gating` is not engaged at all.
- **Non-goal: coverage-delta measurement.** Deferred deliberately: the published evidence says
  coverage gain must be measured rather than assumed, and measuring it well needs a second
  instrumented run per item. That is its own change.

## Why the corpus is synthetic

Two reasons, one governance and one methodological.

**Governance.** A corpus of real internal focal methods would be committed source code from
internal systems, which runs at CHARTER §4 invariant 7 — "No secrets, no machine fingerprints in
the repo… Nothing host-specific is committed" — and would need that invariant relaxed under
CHARTER §6, registered as a §3 Ratified Amendment. `add-production-eval-flywheel` is `Status:
blocked` on exactly that route. A generated corpus touches none of it and needs no decision.

This is a *cheaper* argument than the alternative, not a weaker one: the point is that nothing about
this change requires a governance conversation, so it can start immediately.

**Methodological.** The literature the source plan cites for stratification actually describes
*generation*: the GBCV work builds 786 Python programs from control-flow-graph templates with
p-use/c-use placeholders and states plainly that its dataset "is not extracted from any existing
repository." A generator gives reproducible difficulty strata and unlimited held-out material; a
scraped corpus gives neither, and carries contamination risk on top.

## Impact

- **Protected paths:** `src/eval_harness/scorers/**`, `config/**`, `features.yaml`,
  `scripts/validations/**`, root `tests/**`. Needs `eval-change-approved` + CODEOWNERS review.
- Root `eval_harness` coverage floor **96%**.
- New matrix obligation: 4 scorers × the 5-dimension scorer floor (M1, M2, M3, M5, M6) = **20
  cells**. Under ADR 0032 a rowless component fails the census, and waivers must stay a small
  minority, so these land in this change and not a follow-up.
- `tests/public_surface_baseline.json` and `tests/plugin_registry_baseline.json` regeneration
  (F-039 exact-equality freeze; M7 registry dimension).
- New top-level `corpora/` directory. `check_charter_invariants._MISSION_DIRS` is a presence
  check, not an allowlist, so this adds no charter finding.

## Why the ordering matters

`prove-m8-execution` is mid-flight and replaces M8 composability credit — currently granted the
instant a component's name appears in a validated config — with an execution ledger. Landing four
new scorers before it mints four new provably-vacuous M8 cells, which is the exact
evidence-integrity defect that change exists to remove. Land it first.

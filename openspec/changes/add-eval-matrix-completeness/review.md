# Review: the matrix-completion plan, peer-reviewed before proposal

Two independent passes over the draft plan — a mechanical fact-check (every falsifiable claim
re-derived against the tree at `4ceed30`; verdicts CONFIRMED / CORRECTED / REFUTED) and an
adversarial design review (attacks verified before kept; refuted attacks recorded). This file
records what survived and shaped the proposal; the plan was rewritten under it. House
precedent: `docs/plans/agent-eval-coverage/REVIEW.md`.

## Confirmed premises

- The 7 trajectory scorers (`src/eval_harness/scorers/trajectory.py:189,210,226,246,287,343,390`)
  have **zero** matrix rows; `grep trajectory tests/test_matrix_eval_tools.py` is empty. Only
  `TestM4Interface` reaches them, because it parametrizes `SCORERS.names()` dynamically.
- `TestM7Registry` (`tests/test_matrix_eval_tools.py:75-126`) hardcodes every list; 13 of 23
  registered aliases are asserted nowhere (the 6 non-trajectory: `csv_file`, `parquet_file`,
  `python`, `llm`, `json`, `html`).
- The sparse-cell census: bedrock/phoenix_evals judges, model target, langfuse/braintrust
  datasets, and langfuse/phoenix/braintrust sinks each carry a single dimension; `TestGating`
  has no M6; all three M8 pipelines are echo-target.
- `eval_test_matrix.xlsx` (claimed by `NEXT_STEPS.md:151`) was never committed:
  `git log --all --diff-filter=A -- '*eval_test_matrix*'` is empty. `features.yaml`'s F-045
  entry itself makes no xlsx claim.

## Defects found in the tree during review (fixed by this change)

1. **`config/trajectory_eval.yaml` fails its own gate.** Executed: `trajectory_in_order`
   pass_rate **0.0** against min 0.9; `trajectory_precision_recall` f1 0.0. Its reference says
   `search {q: "widget 42"}` while the item's question is `"what is widget 42"`
   (`tests/_sut.py:32` echoes the question verbatim into the `q` argument), and its `fetch`
   entry declares no arguments while the SUT emits `{"id": "42"}` — under the
   `compare_arguments: True` default both mismatch. The covering test
   (`tests/test_trajectory_integration.py:177-186`) asserts only non-emptiness, so the gate
   failure was invisible.
2. **`--cov=F_052` in `quality-gates.yml:171` is dead.** `tests/test_validation_scripts.py`'s
   import list stops at `F_050`, so the step logs `CoverageWarning: Module F_052 was never
   imported` and measures nothing for it. (Headroom for repair is real: the step measures
   95.08% against its 85 floor.)
3. **`Registry._aliases` has no duplicate guard** (`src/eval_harness/core/registry.py:37-38`)
   — an alias can be silently repointed to a different canonical while still *resolving*.
   Deleting the hardcoded M7 alias pairs without a replacement would leave that undetected by
   any assertion; hence the exact-equality alias-map freeze in this change.

## Corrections that reshaped the design

- **Derived M7 direction.** The committed registry baseline is a *flat union* of names and
  aliases; `Registry.names()` returns canonical keys only — so "every baseline key is in
  `names()`" fails for all 23 aliases. The assertion is `key in registry` +
  `resolve(key) in names()`, and it asserts *resolvability*, not pairing (pairing is the
  freeze above).
- **M8 extraction cannot key off `"type"` literals** — `braintrust`/`langfuse` exist in both
  DATASETS and SINKS, so name→kind is not injective. Replaced with an importable `PIPELINES`
  constant whose kinds are read from `EvalConfig.model_validate` typed fields.
- **`MATRIX_COMPONENTS = REGISTERED` (a cross-file name) is unresolvable by AST.** Class
  attributes must be literal tuples; the anti-hardcoding tension is resolved by the
  checked-declaration principle now recorded in ADR 0032.
- **The sink floor contradicted its own fill list** — three vendor sinks would have needed
  unplanned waivers under `{M1, M3}`. Floors corrected to `sink: {1, 2, 6}` (empty-run emit;
  degrade/error path) with M3/M5 as extras where an artifact exists, and `target` gains M6
  (the model target is the kind's riskiest error surface; echo is waived with a reason).
- **`implemented_in`**: the schema requires it once `status: done`, while the `ae1cfc6`
  derivation ("the commit that added BOTH the ledger entry and its proof") cannot be
  self-referenced. Resolution: land the entry `in_progress` alongside the proof, flip to
  `done` + that commit's SHA in a later commit of the same PR.
- **Same-PR archiving had no precedent and no defined stamp SHA** — archival moves to a
  post-merge follow-up stamped with the real merge SHA, matching how `ae1cfc6` archived the
  previous four changes.
- Smaller pins now recorded in the tasks: `on_missing`'s ValueError requires a non-numeric
  *string* (`None` is TypeError); the unknown-kwarg TypeError raises from
  `_TrajectoryScorer.__init__`; gate `metric` rejection surfaces as
  `pydantic.ValidationError` (field_validator, not an enum); the callable target swallows SUT
  exceptions into `TargetOutput.error`, so the M8 pipeline asserts `error is None`; trajectory
  failure comments render name lists that are identical under args-only mismatches, so matrix
  assertions bind to `passed`/`value` only.

## Attacks that died under verification (kept per house style)

- "Skills hardening will red existing skills' CI" — refuted: all nine Schema-A eval files
  carry ≥2 cases and the union of used assertion types already covers all seven registered
  graders. (Recorded as a pre-flight inventory task in `extend-matrix-to-fleet`.)
- "A doc-only hand edit escapes CI" — refuted once `eval-harness-ci.yml`'s path filters
  include the generated doc: doc-only PR → `make check` → freshness test red.
- "The derived M7 in-process read is unsafe" — refuted for the asserted direction: `_reg` is
  add-only (`register_class` raises on a differing duplicate), and a dropped builtin masked by
  a double still fails the subprocess surface guard. The docstring carries the scoping.

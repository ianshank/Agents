# Change: prove-m8-execution

**Status:** proposed · **Date:** 2026-09-02 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/eval-evidence-integrity/REVIEW.md` — peer review of an
eval-tool test-matrix readiness brief. Its own headline recommendation (widen M8
composability to all 41 registered components) is withdrawn in that review (Pass 2, A2): the
mechanism it would widen counts config presence, not execution, and already contains a
provably vacuous cell.
**Compiles down to:** `docs/plans/eval-evidence-integrity/PLAN.md` Phases 2-4 + F-IDs
(claimed at land) + a design ADR for the judge `client=` seams.

## Why

`tests/_matrix_coverage.py`'s M8 (Composability) dimension is discharged by
`pipeline_kinds()` (`:744-771`), which reads a validated `EvalConfig` dict and records which
component `type` values it names. A component is credited the instant its name appears in a
config that passes Pydantic validation — never once its actual protocol method (`Scorer.score`,
`Judge.evaluate`, `DatasetSource.load`, and so on) is observed to run.

This is demonstrated, not theorised. The `echo_exact_match` pipeline in
`tests/test_matrix_eval_tools.py:1438` declares `"judge": {"type": "mock"}` and is credited
in `docs/matrix-coverage.md`'s "M8 pipelines — kinds exercised" table for `judge/mock`. Its
two scorers, `exact_match` and `contains`, are not judge-backed. Instrumented for this
proposal, `MockJudge.evaluate` is called **zero times** by that pipeline. The matrix already
contains a vacuous M8 cell, and nothing in the matrix's own machinery — including its
census-level vacuity guard (`test_an_empty_census_never_satisfies_the_floors_vacuously`) —
can see it, because that guard operates on the registry census, not on execution.

Widening M8 to a 41-component floor on the current mechanism, as the reviewed brief proposed,
would industrialise this defect rather than close it. Worse, two of the candidate cells are
actively unsafe on the current mechanism: `OpenAIJudge` and `AnthropicJudge` construct real
SDK clients in `__init__` (`src/eval_harness/judges/__init__.py:101-122`, `:250-265`) with no
injection seam. A pipeline naming `openai` alongside an `llm_judge` scorer would attempt real
network egress from CI and still report green — the engine converts a connection error into
a `0.0`-valued `ScoreResult` with a `"scorer error: ..."` comment
(`src/eval_harness/engine.py:224-231`) rather than raising. Verified by execution against
this checkout.

## What changes

- A new execution ledger (`tests/_m8_probe.py`) that patches `Registry.create` — the single
  construction choke point for all six kinds — to wrap each constructed component's protocol
  method with an invocation counter, so `panel`'s member judges and `weighted`'s child
  scorers are credited automatically through the same seam real usage goes through.
- `tests/_matrix_coverage.py` gains `pipeline_execution_census()` alongside the existing
  `pipeline_kinds()` — kept, not replaced, so `docs/matrix-coverage.md` can publish *declared
  minus executed* as an honest vacuity metric rather than erasing the old accounting.
- A cell-level vacuity refusal, mirroring the existing census-level one, so a matrix pipeline
  that declares a component it never invokes fails the freshness gate rather than silently
  crediting it.
- A session-scoped egress guard (patching `socket.socket.connect` to raise for non-loopback
  addresses, scoped to the matrix suite by marker) so a judge that does attempt a real
  network call fails loudly instead of degrading to a swallowed `0.0` score.
- Breadth: the 19 components composable today with zero production change (recording null
  clients for `phoenix`/`braintrust` sinks, `panel` over mock members, `sqlite`/`filesystem`/
  `mock_http` adapters, `html_file`/`jsonl` datasets, `langfuse`/`braintrust` datasets via
  existing test doubles) plus `csv`, `parquet`, and the `langfuse` sink, which are already
  engine-composed in `tests/integration/test_pipeline_e2e.py` and `tests/test_engine.py` but
  uncredited by the matrix's own accounting.
- A `client: Any | None = None` dependency-injection seam on `OpenAIJudge.__init__` and
  `AnthropicJudge.__init__`, mirroring `ModelTarget`'s existing, documented seam
  (`src/eval_harness/targets/model.py:112-129`) exactly, so the two riskiest judges become
  matrix-testable without ever constructing a real SDK client offline.

## Scope / non-goals

- **Non-goal: M8 as a `REQUIRED_DIMS` floor.** M8 measures a different thing (did the
  component's code path execute) from M1/M2/M3/M5/M6 (how many test methods exist per
  dimension). Forcing it into `_GRID_DIMS` would need a non-count rendering branch in
  `_render_kind_section` (every other cell is an integer method count) and collides with
  `_collect_cells`'s active refusal of `MATRIX_COMPONENTS` on extra suites
  (`tests/_matrix_coverage.py:592-601`). The execution census is its own artifact section,
  not a seventh grid column, and needs no ADR 0032 amendment.
- **Non-goal: `bedrock` and `phoenix_evals` judge cells.** Neither can construct in the
  matrix CI job today — `boto3` and `arize-phoenix-evals` are both absent from
  `eval-harness-ci.yml`'s install line, and `phoenix_evals` has no `_EXTRA_PROVIDES` entry.
  `phoenix_evals`'s pandas/numpy footprint against the `pyarrow>=14,<20` pin
  (`pyproject.toml:66-68`) is an open question `phoenix-live.yml`'s existing `dep-resolve`
  job should answer first. Both cells are waived with these named reasons, not silently
  dropped.
- **Non-goal: mutation testing.** No `mutmut`/`cosmic-ray` tooling exists in this repository
  and none is introduced here. The execution ledger plus the cell-level vacuity refusal
  address the specific failure class this repository has been burned by twice (cells whose
  single test asserted nothing) without a new test-execution framework.
- **Non-goal: fleet extension.** Sibling packages are out of scope for this change; see the
  separate, not-yet-created `extend-matrix-to-fleet` change (`docs/plans/eval-evidence-integrity/PLAN.md`
  Phase 9).
- **Non-goal: widening the egress guard beyond the matrix suite.** Patching `socket.connect`
  repo-wide would likely surface other tests that quietly dial out — a legitimate finding,
  but separate scope from this change.

## Impact

- New `tests/_m8_probe.py` and edits to `tests/_matrix_coverage.py`,
  `tests/test_matrix_coverage.py`, `tests/test_matrix_eval_tools.py`, `tests/conftest.py` —
  all under the protected `tests/**` pattern, needing the `eval-change-approved` label.
- `src/eval_harness/judges/__init__.py` (`OpenAIJudge`/`AnthropicJudge` constructors) —
  protected under `src/eval_harness/judges/**`; ships with its own design ADR and regenerates
  `tests/public_surface_baseline.json` in the same PR (a protected path itself, so this piece
  cannot be split unprotected-first).
- `features.yaml` + `scripts/validations/F_0NN.py` (F-ID claimed at land) proving a pipeline
  declaring an uninvoked component is rejected, and that constructing each judge with an
  injected client performs zero socket connects.
- `docs/matrix-coverage.md` regenerated with a new execution-evidence section.

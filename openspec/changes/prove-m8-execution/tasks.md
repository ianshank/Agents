# Tasks: prove-m8-execution

**Status: all tasks implemented.** Tasks 1-2 landed earlier on this change (`f118b07` and
predecessors). Task 5 and its F-ID landed as **F-063**; `python scripts/validations/F_063.py`
is the executable proof. Task 4 (breadth) landed 2026-09-05: **M8 now credits 39 of the 41
registered components, and the two uncredited are exactly the two waived.** The change is
ready for archive once the `spec-guardian` and `peer-reviewer` passes run.

`[P]` = protected path; needs `eval-change-approved` + CODEOWNERS review.
Coverage floor: **96%** (root `eval_harness`).

## 1. Execution ledger machinery — PR 3

- [x] `[P]` New `tests/_m8_probe.py`: `ExecutionLedger`, `probe()` context manager patching
      `Registry.create`, `_PROTOCOL_METHODS` checked declaration cross-checked at import
      against `core/interfaces.py`.
- [x] `[P]` `_assert_no_swallowed_errors(result)` helper: no `ItemResult` is an exception; no
      `ScoreResult.comment` starts with `"scorer error: "`.
- [x] `[P]` `tests/conftest.py`: `matrix_offline` marker + autouse fixture patching
      `socket.socket.connect` to raise for non-loopback addresses, scoped to that marker only.
- [x] No policy change and no new assertion on any existing test in this PR — it must be
      reviewable purely as machinery, per `docs/plans/eval-evidence-integrity/PLAN.md`'s PR
      decomposition.

## 2. Turn the ledger on; fix the vacuous cell — PR 4

- [x] `[P]` `TestM8Composability` in `tests/test_matrix_eval_tools.py`: run pipelines inside
      `probe()`; add one execution assertion per existing pipeline
      (`ledger.invoked(kind, component)`), plus `_assert_no_swallowed_errors`.
- [x] `[P]` **Expected: `test_m8_full_pipeline_echo_exact_match` fails first.** Fix by adding
      an `llm_judge` scorer to that pipeline (or dropping the unused `judge: mock`
      declaration) — either way, land the failing-then-fixed commit pair so the mechanism's
      ability to falsify is visible in history, not just asserted in prose.
- [x] `[P]` `tests/_matrix_coverage.py`: `pipeline_execution_census()` beside
      `pipeline_kinds()` (kept); publish declared-minus-executed.
      **Shipped as `pipeline_vacuous()` + `pipeline_declared()`, not under the proposal's
      name.** Same contract: the diff is taken per pipeline, never as a repo-wide union.
- [x] `[P]` `tests/test_matrix_coverage.py`: cell-level vacuity refusal mirroring
      `test_an_empty_census_never_satisfies_the_floors_vacuously`.
- [x] `[P]` New `_render_execution_section` in `tests/_matrix_coverage.py`'s renderer:
      components × {invoked / declared-only / absent}, its own section in
      `docs/matrix-coverage.md`, not a `_GRID_DIMS` column.
- [x] `[P]` Regenerate `docs/matrix-coverage.md` (`python tests/test_matrix_coverage.py --update`).

## 3. Feature record — PR 5

- [x] `[P]` `features.yaml` F-ID (claimed at land) + `scripts/validations/F_0NN.py`: proves a
      pipeline declaring a component it never invokes is rejected by the execution census
      (an executable regression test for task 2's `echo_exact_match` finding).

## 4. Breadth: the 19 test-only components — PR 6/7 — **DONE**

- [x] `[P]` Generalise `_run`'s tmp-path override into a table keyed by `(kind, type)`.
      Shipped as TWO tables, not one: `TMP_PATH_PARAMS` for components that WRITE an
      artifact and `TMP_FIXTURE_PARAMS` for inputs a test must materialise first (a `csv`
      dataset needs a real file on disk before `EvalConfig` is even validated). Conflating
      them would make `_run`'s single return value mean two things. Keyed by `(kind, type)`
      and not type alone, because `braintrust` and `langfuse` are each registered under two
      kinds — asserted by a test against the live census.
- [x] `[P]` `PIPELINES` values become zero-arg factories. **Not done, and deliberately: the
      conversion turned out to be unnecessary.** The AST precondition was discharged first
      (`extract_registries.py` never references `test_matrix_eval_tools`; every consumer reads
      `PIPELINES` at runtime), and then all nineteen cells were built without a single factory.
      A deep copy per run already isolates a literal, including the live recording clients the
      judge and model-target cells inject; a path that must be built per test comes from the
      tables above; a client injected at engine construction comes from a `_run` parameter; and
      a cell needing `sys.modules` faked has its TEST METHOD request the `fake_braintrust`
      fixture. A hybrid literal/factory seam was built, proved to have zero consumers, and
      removed — an unused mechanism guarded by tests is the same declared-but-never-invoked
      shape this change exists to refuse.
- [x] `[P]` Add pipelines, cheapest first: `phoenix`/`braintrust` sinks through
      `NullPhoenixScoreClient.scores`/`NullBrainTrustClient.items` (zero config,
      `enabled=False` default); `panel` over `{"type": "mock"}` members;
      `langfuse`/`braintrust` datasets via `NullLangfuseClient(dataset_items=...)` and the
      existing `fake_braintrust` fixture (`tests/conftest.py:79-119`); `sqlite`
      (`:memory:`); `filesystem` (tmp root); `mock_http`; `html_file`; `jsonl`.
- [x] `[P]` Credit `csv`, `parquet`, and the `langfuse` sink by adding them to `PIPELINES`
      (they already run in `tests/integration/test_pipeline_e2e.py` and `tests/test_engine.py`
      respectively; this task makes the matrix's own accounting agree, keeping the ledger
      single-sourced rather than counted from outside tests).
- [x] `[P]` Regenerate `docs/matrix-coverage.md`. **M8 now credits 39 of 41 components; the
      two uncredited are exactly the two waived (`bedrock`, `phoenix_evals`).**

## 5. Judge DI seams — PR (own protected PR, cannot split unprotected-first)

- [x] `[P]` `client: Any | None = None` on `OpenAIJudge.__init__`
      (`src/eval_harness/judges/__init__.py:101-122`) and `AnthropicJudge.__init__` (`:250-265`),
      mirroring `ModelTarget`'s seam; move the SDK import inside `if client is None:`.
- [x] `[P]` M8 pipelines for `openai`/`anthropic` using recorded fake clients, asserted
      through the ledger **and** the `matrix_offline` egress guard from task 1.
      **Both.** An earlier draft of this line shipped `openai` only and waived `anthropic`
      on the reason "absent from `eval-harness-ci.yml`'s install line" — which was simply
      false: `dev` pulls `anthropic>=0.40` (`pyproject.toml:87`), so the SDK was never
      absent from the matrix job. The waiver was removed and the cell built.
      `AnthropicJudge.evaluate` imports nothing, so with an injected client that judge
      touches its SDK at neither construction nor call time; `OpenAIJudge.evaluate` still
      imports `openai` for its retry predicate, which is why the seam's claim is scoped to
      construction. Both cells assert the judge's *parsed verdict*, against two distinct
      fixture scores so neither can pass by reading the other's.
- [x] `[P]` `python tests/test_public_surface.py --update` in the same PR (protected path;
      cannot be split from the constructor-signature change).
- [x] `[P]` `features.yaml` F-ID: constructing each judge with an injected client performs
      zero socket connects.
- [x] `[P]` `scripts/validations/F_063.py` proves the seam is load-bearing **by execution**.
      Recorded because the first cut did not, and an automated PR review caught it: that
      version read the pipeline dict and the fixture's score constant and concluded *from
      their shape* that the cell was falsifiable — crediting a declaration instead of an
      execution, which is the exact defect this change exists to remove, reintroduced inside
      the validator that proves the change. It now runs each seam judge's pipeline end to end
      twice against two different injected verdicts and requires the aggregate to follow, with
      the egress guard armed at `socket.connect`. Negative controls executed against this
      checkout: a constant-answering judge fails 4 checks; a constructor that discards the
      injected client fails 8, including the egress assertion.
- [ ] New ADR for the seam (own document, referenced from this change's design.md).
      **Not written.** The seam is a two-line constructor change that copies
      `ModelTarget`'s already-ADR'd pattern verbatim rather than deciding anything new;
      F-063's `verification` bullets and this change's `design.md` carry the reasoning.
      Raise it at review if a separate ADR is still wanted before archive.
- [x] Waive `bedrock`/`phoenix_evals` M8 cells explicitly, with the reasons in proposal.md's
      non-goals, rather than leaving them silently absent. Shipped as `M8_WAIVED`
      (`tests/_matrix_coverage.py`), rendered into `docs/matrix-coverage.md` and hygienic in
      both directions: a waiver a live cell has satisfied fails as stale, and a waiver naming
      an unregistered component fails as a typo. The anthropic entry was removed under the
      first of those rules once its cell was built.

## 6. Verification

```bash
python -m pytest tests/test_matrix_eval_tools.py::TestM8Composability -q   # expect RED before task 2's fix, GREEN after
python -m pytest tests/test_matrix_eval_tools.py tests/test_matrix_coverage.py -q
python tests/test_matrix_coverage.py --check
python -m pytest tests/test_public_surface.py -q
python tests/test_public_surface.py --update
python scripts/check_size_budget.py
python -m pytest --cov=eval_harness --cov-branch --cov-fail-under=96
make determinism
```

# Tasks: add-testgen-eval-matrix

`[P]` = protected path (`eval-change-approved` label + CODEOWNERS review).
Coverage floor: root `eval_harness` **96%** (`coverage-floors.yaml`).
**Status: implemented, pending archive.** Both blockers landed first, as the change required:
`add-gate-decision-provenance` as F-062 and `prove-m8-execution` (including task 4's breadth)
before any scorer here was written. Claimed **F-065**; ADR **0043**.

## 1. Corpus

- [x] 1.1 Write the generator: focal methods from control-flow templates with p-use/c-use
      placeholders, seeded deterministically. Not scraped from any repository — see
      `proposal.md` "Why the corpus is synthetic".
- [x] 1.2 For each focal method emit a known-correct reference implementation, a non-equivalent
      mutant set with equivalence marks, and a gold obligation set.
- [x] 1.3 Freeze 60 items at `corpora/testgen/v1/` with a manifest carrying `schema_version`, the
      generator seed, per-item hashes, and the control-flow stratum of each item.
- [x] 1.4 Hold out a sequestered split that is not used while iterating scorers. Reuse
      `flow_corpus.holdout` idioms for the keying rather than inventing a split scheme —
      `holdout/{manager,rotation}.py` already exists.
- [x] 1.5 Add `corpora/README.md` stating what belongs here and, explicitly, why this is not
      `flow-corpus/` (that package is synthetic-only, airgapped from the harness by F-011, and
      keeps its data at `data/suites/`).

## 2. Execution target

- [x] 2.1 Implement the suite-execution callable target: collect, run against the reference
      implementation, run against each mutant, emit the evidence payload in
      `TargetOutput.metadata["testgen_evidence"]`.
- [x] 2.2 Bound it — per-item working directory, wall-clock limit, timeout recorded as evidence
      rather than raised. Confirm interaction with the existing item-error policy (ADR 0038) so a
      timeout does not abort the run.
- [x] 2.3 **[P]** Add the target to `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST` explicitly (ADR 0039,
      deny-by-default). Test that an unlisted target is refused *before* any generated code runs.
- [x] 2.4 Confirm the offline property: the target executes generated code but opens no socket and
      needs no external service. Note in the test that `--offline` selects an in-memory Langfuse
      client and is **not** a network kill-switch — the zero-dependency property comes from the
      suite itself, so assert it directly.

## 3. Scorers

- [x] 3.1 **[P]** `test_executability` — collectable and runnable; zero collected tests is a
      failure, not a pass.
- [x] 3.2 **[P]** `testgen_mutation_score` — raw and normalized, both labelled with their
      denominator, equivalent mutants excluded from both.
- [x] 3.3 **[P]** `testgen_green_on_correct` — false-alarm rate against the reference
      implementation, emitted as its own score and never blended into 3.2.
- [x] 3.4 **[P]** `requirement_obligation_recall` — covered ÷ declared gold obligations, in [0,1],
      never inferred from the generated tests.
- [x] 3.5 **[P]** All four report "not applicable" (`passed=None`) on absent evidence, following
      the `state.py` precedent. Test that a missing payload is distinguishable from a zero score.
- [x] 3.6 **[P]** Assert purity: each scorer scored twice over one payload yields identical values,
      and none starts a subprocess, opens a socket, or writes outside the run's outputs.
- [x] 3.7 **[P]** Split across `scorers/test_generation/{__init__,execution,mutation}.py`; confirm
      each file is under `MAX_FILE_LINES = 500` and each function under the 50-line warn budget.

## 4. Matrix, surface and registry

- [x] 4.1 **[P]** Add matrix rows for all four scorers across the scorer floor M1, M2, M3, M5, M6 —
      **20 cells**. A rowless component fails the census (ADR 0032); these land here, not in a
      follow-up. Do not discharge them with waivers: ADR 0032 §3 keeps waivers "a small minority"
      and self-guards them both ways.
      **Cells are not methods.** `_matrix_coverage.py:645` applies a class's declared dim set to
      *every* name in its `MATRIX_COMPONENTS`, so one parametrized method can discharge a whole
      column. Follow `TestTrajectoryScorersShared` (`tests/test_matrix_eval_tools.py:789`), which
      covers M2/M3/M5/M6 for all seven trajectory scorers in eight parametrized methods. Two
      constraints: matrix classes **must not inherit** (`_matrix_coverage.py:609-618` — inherited
      `test_m*` methods are invisible to the AST map and the guard refuses), and the
      literal-parametrize ban applies only to `Test*Registry` classes, so ordinary scorer classes
      may parametrize freely.
- [x] 4.2 **[P]** Regenerate `docs/matrix-coverage.md`
      (`python tests/test_matrix_coverage.py --update`); freshness is gated by
      `test_matrix_doc_is_fresh`.
- [x] 4.3 **[P]** Regenerate `tests/public_surface_baseline.json` — F-039 freezes `__all__` with
      exact equality, so four additions must be frozen explicitly. **No-op, and correctly so:**
      the surface guard freezes `__all__` per module, the scorers subpackage declares none
      (following `state.py` and `trajectory.py`), and `TESTGEN_EVIDENCE_KEY` was deliberately
      kept out of `core.__all__`. Registry names are the public contract here, and those are
      frozen by `plugin_registry_baseline.json` instead.
- [x] 4.4 **[P]** Regenerate `tests/plugin_registry_baseline.json` for the M7 registry dimension.
- [x] 4.5 Update the scorer registry tables in **both** `README.md` and
      `src/eval_harness/README.md` (`scripts/extract_registries.py:259` names both).
- [x] 4.6 Regenerate the e2e matrix workbook if the run touches it
      (`tests/test_e2e_matrix.py --update`, needs the `e2e-matrix` extra).

## 5. Gating

- [x] 5.1 **[P]** Ship one **advisory** rule per scorer in `config/`. No blocking threshold in this
      change. Bounds are soak starting points in config, not spec values.
- [x] 5.2 **[P]** Wire `repetitions: 5` + `metric: pass_power_k` on `test_executability` rather
      than registering a flake-rate scorer.

## 6. Validation and index

- [x] 6.1 **[P]** Add `scripts/validations/F_0NN.py` pinning: an unlisted execution target is
      refused; absent evidence yields "not applicable" rather than zero; both mutation denominators
      are emitted. F-numbers are claimed at land, never reserved here.
- [x] 6.2 Claim the F-ID in `features.yaml` with `verification` bullets mirroring the spec
      scenarios; set `implemented_in`.
- [x] 6.3 Add this change to "Current changes" in `openspec/README.md` as a **link target** — the
      index guard (`.github/workflows/docs.yml:139`) matches `](target)`, not prose.
- [x] 6.4 Dry-run against the held-out split (11 items x 4 reference suites); distribution
      recorded in `review.md`. The corpus ships four reference suites per item rather than a
      known-good/known-bad pair, because two failure shapes — non-executable and
      false-alarm — must stay distinguishable from a merely low score, and a single "bad"
      class would have conflated them.
- [x] 6.5 Run `./scripts/quality-gate.sh all` and `make check-all`; confirm the 96% floor.
- [x] 6.6 Record the `spec-guardian` and `peer-reviewer` passes in `review.md` (advisory, never
      CI-blocking).

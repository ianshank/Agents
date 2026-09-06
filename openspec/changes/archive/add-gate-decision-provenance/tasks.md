# Tasks: add-gate-decision-provenance

**Status: implemented.** Landed as **F-062**; `python scripts/validations/F_062.py` is the executable proof.

`[P]` = protected path (`eval-change-approved` label + CODEOWNERS review).
Coverage floor: root `eval_harness` **96%** (`coverage-floors.yaml`).

## 0. Authority

- [x] 0.1 **Done: `docs/decisions/0042-gate-decision-provenance.md`.** Draft the design ADR authorising an additive `RunResult.gate` field and moving gate
      evaluation ahead of the sink loop. ADR 0031 covers agent evaluation only and does **not**
      cover this; do not begin implementation on its authority. Next free number is 0042;
      F-numbers are claimed at land, never reserved.

## 1. Persist the decision

- [x] 1.1 **[P]** Add `gate: GateResult | None = None` to `RunResult`, appended last, omitted from
      `to_dict()` when unset. Assert byte-identical serialisation against a pre-change fixture for
      a run with no gate configured.
- [x] 1.2 **[P]** Evaluate the gate inside `EvalEngine.run()` before the sink loop
      (`engine.py:411`), and attach the result.
- [x] 1.3 **[P]** Decide the import direction empirically: declare `engine → gating` in
      `architecture.yaml`, **or** inject a `gate_evaluator` callable from `from_config` so no new
      edge appears. Run `grimp` both ways, take the cheaper one, and record which in `review.md`.
      Regenerate `architecture.mmd` if the manifest changed.
      **Both, and the injection alone was not sufficient — see `review.md` R2.** The edge is
      declared; `drift_check.py` reports "Architecture matches the manifest" and
      `architecture.mmd` is regenerated.
- [x] 1.4 **[P]** Make the CLI read `run.gate` rather than calling `evaluate_gate` itself
      (`cli.py:92`). Assert the recorded decision and the exit code derive from one evaluation —
      two evaluations could disagree between the artifact and CI.
- [x] 1.5 **The sink did not render it; implemented here, not just asserted.** Assert the `html_file` sink renders the decision. This is the artifact the VP deliverable
      is generated from and the reason this change exists.

## 2. Advisory rules

- [x] 2.1 **[P]** Add `report_only: bool = False` to `GateRule` (`config/models.py`). Optional with
      a default, so `SCHEMA_VERSION` is untouched and `from_dict` stays strict.
- [x] 2.2 **[P]** Confirm `_require_at_least_one_bound` still rejects a bound-less rule when
      `report_only` is true. Add the negative test; do not relax the validator.
- [x] 2.3 **[P]** Add `advisory: list[dict[str, Any]]` to `GateResult`, appended last.
- [x] 2.4 **[P]** Route an unmet rule to `advisory` or `failures` at the filing point, keeping one
      evaluation path. Assert the single-path property directly: evaluate the same run both ways
      and compare verdicts.
- [x] 2.5 **[P]** Assert an advisory rule never softens a blocking failure in the same run.
- [x] 2.6 **[P]** Restrict `require_calibration_for_judge_gating` to non-advisory rules. Three
      tests: advisory judge-backed rule accepted without an artifact; blocking one still rejected;
      promotion re-arms the rejection.

## 3. CLI reporting

- [x] 3.1 **[P]** Report advisory outcomes in a section visibly separate from failures.
- [x] 3.2 **[P]** Assert the exit code is unchanged by advisory outcomes, and that a blocking
      failure in the same run still exits non-zero.

## 4. Matrix, surface and docs

- [x] 4.1 **[P]** Confirm against `tests/_matrix_coverage.py` that `gating` is not a `MATRIX_KIND`
      and no new matrix rows are owed. Record the confirmation here rather than assuming it; if
      rows *are* owed they land in this change, not a follow-up (ADR 0032).
      **Confirmed:** `REQUIRED_DIMS` keys are `dataset, judge, scorer, sink, state_adapter,
      target`. `gating` is not among them; zero rows owed.
- [x] 4.2 **[P]** Regenerate `tests/public_surface_baseline.json` — F-039 freezes `__all__` with
      exact equality, so an addition must be frozen explicitly, not only a removal.
- [x] 4.3 Update the gate documentation in `README.md` and `src/eval_harness/README.md` if either
      enumerates rule fields (`scripts/extract_registries.py:259` names both as doc paths).
      **Root `README.md` does not enumerate rule fields; `src/eval_harness/README.md`'s module
      table row for `gating/` now documents both new behaviours.** Registry check passes
      unchanged (no new registered components).
- [x] 4.4 Add this change to "Current changes" in `openspec/README.md` as a **link target**. The
      index guard (`.github/workflows/docs.yml:139`) matches `](target)`, not prose — a change
      directory named only in a sentence fails CI.

## 5. Validation

- [x] 5.1 **[P]** Add `scripts/validations/F_0NN.py` pinning: the gate decision reaches the sinks;
      an advisory rule that fails does not fail the run; a blocking rule that fails still does.
- [x] 5.2 Claim the F-ID in `features.yaml` with `verification` bullets mirroring the spec
      scenarios; set `implemented_in` to the landing commit.
- [x] 5.3 Run `./scripts/quality-gate.sh all` and `make check-all`; confirm the 96% floor.
- [ ] 5.4 Record the `spec-guardian` conformance pass and the `peer-reviewer` adversarial pass in
      `review.md` (advisory, never CI-blocking — `openspec/AGENTS.md`).
      **Not run as separate fleet roles.** Both are `claude-foundation/` agents, which are
      staged in-tree rather than installed (ADR 0028) and need a session started with
      `claude --plugin-dir claude-foundation`. `review.md` records the implementation findings
      inline instead; the conformance pass is owed before archive.

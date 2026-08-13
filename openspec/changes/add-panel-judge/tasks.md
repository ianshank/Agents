# Tasks: add-panel-judge

`[P]` = protected path; needs `eval-change-approved` + CODEOWNERS review.
Coverage floor: **96%** (root `eval_harness`).

## 1. Panel component — PR 1

- [ ] `[P]` `PanelJudge` in `src/eval_harness/judges/`, registered `panel`, no alias.
- [ ] `[P]` Members built once at construction via `JUDGES.create`; raise on empty list,
      non-mapping spec, missing `type`, unknown strategy.
- [ ] `[P]` Strategies as an enumerated tuple: `median` (default), `mean`, `majority`
      (binarised at `member_pass_threshold`, default on the field).
- [ ] `[P]` Per-member breakdown, spread, stdev, strategy and abstention flag in
      `JudgeVerdict.raw`; no core-model change.
- [ ] `[P]` Abstention on spread > `disagreement_threshold` and on below-quorum survival
      (quorum denominator = **configured** members); abstain verdict uses the `on_skip`
      config field — the existing name for "this evaluator declined to score"
      (`AutoevalsScorer.on_skip`) — and names its reason.
- [ ] `[P]` **Abstention must survive the scorer boundary** (review C5): `LLMJudgeScorer`
      gains an abstention-aware path emitting `passed=None`, mirroring
      `AutoevalsScorer`'s skip branch (`scorers/__init__.py:307-313`). Without this an
      abstention arrives as `passed=False` and the component is worse than useless.
      `src/eval_harness/scorers/**` is protected.
- [ ] `[P]` Reject a single-member panel at construction (spread is structurally 0).
- [ ] `[P]` Aggregate via `statistics` (`median`/`fmean`/`pstdev`) — already this package's
      dependency (`engine.py:12`); do not hand-roll. Document even-N `median` behaviour.
- [ ] `[P]` Members evaluated sequentially in declaration order (the determinism guarantee
      depends on it).
- [ ] `[P]` Member exceptions excluded and recorded in `raw["failed_members"]`; a panel
      outage yields a fail-safe verdict, never a crashed run.
- [ ] `[P]` `attach_client` fan-out to every member.
- [ ] `[P]` Module-level `logger = logging.getLogger(__name__)` (no `basicConfig`); `debug`
      per member call, `warning` on member failure and on abstention — see `design.md`
      "Logging". Test with `pytest -o log_cli=true --log-cli-level=DEBUG`.
- [ ] All config values are constructor params with documented defaults on the field — no
      call-site literals.

## 2. Budget accounting — `agent_core_adapter` (unprotected) — PR 1

- [ ] `build_budgeted_judge` / `BudgetedJudge` read duck-typed `calls_per_evaluate`
      (absent → 1) and reserve cost and rate-window slots per member call.
- [ ] `PanelJudge.calls_per_evaluate = sum(getattr(m, "calls_per_evaluate", 1) for m in
      members)` — **not** `len(members)`, which under-charges nested panels by the same
      mechanism this task exists to fix (review C6).
- [ ] Assert an N-member panel under a cap sized for fewer than N calls trips the budget on
      the first evaluation — the under-charge regression test.

## 3. Matrix + baselines — PR 1

- [ ] `[P]` Matrix rows for kind `judge` to the M1/M2/M3/M6 floor
      (`tests/_matrix_coverage.py`), declared with literal `MATRIX_KIND`/`MATRIX_COMPONENTS`,
      exercised via the registered-name path with `MockJudge` members only.
- [ ] `[P]` **M5 (determinism) rows too, above the floor.** `REQUIRED_DIMS["judge"]` excludes
      M5 because "verdict determinism is the provider's" — that rationale does not hold for a
      panel, whose aggregation, quorum and abstention logic are repo-owned. The policy
      comment explicitly welcomes subset-meaningful dims as extra rows.
- [ ] `[P]` Add the `add-panel-judge` row to `FOLLOW_ON` in `tests/_matrix_coverage.py`
      alongside the three sibling changes, and regenerate `docs/matrix-coverage.md`. Must be
      added **while `panel` is still unregistered** — the guard fails a FOLLOW_ON row whose
      component already exists in the census.
- [ ] Add `panel` to the judges list in **both** `README.md` and
      `src/eval_harness/README.md` — the advisory `registry-drift` job in `docs.yml` compares
      registered names against both.
- [ ] `[P]` Regenerate `tests/plugin_registry_baseline.json` and
      `tests/public_surface_baseline.json`; `python tests/test_matrix_coverage.py --update`
      for `docs/matrix-coverage.md`.
- [ ] Verify `architecture.yaml` is **unchanged** — the panel is a registration, not a
      component edge.

## 4. Calibration obligations — PR 2

- [ ] Panel-level κ versus human labels via `agent_core.golden.cohen_kappa`, under the
      held-out and power discipline `extend-judge-calibration` establishes.
- [ ] Pairwise member–member κ (redundancy) and abstention rate carried in the calibration
      artifact; member model families declared in config and reported.
- [ ] `[P]` Assert a panel without a named calibration artifact cannot gate — the
      `extend-judge-calibration` rule applied to the aggregate.

## 5. Documentation — PR 2

- [ ] Config example (`config/` is protected — example YAML in docs, not a new shipped
      config) and README judges-table row.
- [ ] Design ADR at `docs/decisions/NNNN-panel-judge.md` compiling down from this package's
      `design.md`.

## 6. Governance — PR 3

- [ ] `[P]` Claim the next free F-ID in `features.yaml`; verification bullets name the
      executing tests and the mutation each would catch.
- [ ] `[P]` Add an executable `scripts/validations/F_0NN.py` proof — one check per spec
      scenario.
- [ ] CHANGELOG entry under the current dev section.

## 7. Verification

- [ ] Full gate suite (`make check-all`) **plus** the `quality-gates.yml` tail that
      `check-all` does not cover: `scripts/validate.py --tier fast --strict`,
      `check_size_budget.py`, `check_guard_reachability.py`, `check_charter_drift.py`,
      `check_charter_invariants.py`, `check_skill_script_drift.py`. Matrix freshness green.
- [ ] End-to-end offline, one assertion per edge case found in review:
      a three-`MockJudge` panel is byte-deterministic and calls members in declaration order;
      a disagreeing panel abstains rather than averaging, and that abstention reaches the
      result as `passed=None` (not `False`); a below-quorum panel abstains; an N-member panel
      consumes N budget reservations and a **nested** panel consumes its members' members;
      a one-member panel is rejected at construction; `median` over an even-sized panel is
      documented as the mean of the middle two.

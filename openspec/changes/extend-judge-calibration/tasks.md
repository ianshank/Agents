# Tasks: extend-judge-calibration

`[P]` = protected path. Coverage floors: `agent-core` **95%**, root `eval_harness` **96%**.

## 1. Probe math — `agent_core` (unprotected)
- [x] Add paired-order transformation and order-flip rate.
      New `agent_core/judge_calibration.py::order_flip_rate(verdicts_ab, verdicts_ba, cfg)` —
      `verdicts_ba` is translated back to original-answer terms via a swap table before
      comparing, since "a" in the swapped ordering means the *first-shown* candidate (B) won.
      CI via the existing `wilson_interval`, no new interval math.
- [x] Add controlled verbosity transformation and preference delta.
      `verbosity_preference_delta(verdicts, cfg)` — `preference_delta` is `expanded_win_rate -
      0.5` (deviation from the unbiased 50/50 expectation) among non-tied pairs; ties are
      counted but excluded from the rate. `passes` is symmetric (`abs(delta) <= tolerance`):
      a judge that penalises length is also a biased judge, not just one that rewards it.
- [x] Add judge-family metadata and self-preference breakdown.
      `self_preference_breakdown(judge_family, outcomes: Sequence[PairOutcome], cfg)` — a new,
      minimal `PairOutcome(family_a, family_b, winner)` record, deliberately independent of the
      Group 2 corpus type (probe math has no dependency on where a pair came from). Only pairs
      where exactly one candidate is `judge_family` are informative; `other_family_win_rate` is
      always `1 - same_family_win_rate` for a non-tied informative pair, reported anyway for
      readability. `passes` is one-sided (`delta <= tolerance`) — the check is specifically
      about the judge favouring its own family, per spec.md's literal framing.
- [x] Frozen dataclass config; no YAML knobs, no numeric literals at call sites.
      New `ProbeConfig` in `agent_core/config.py`, registered in `FrameworkConfig` (import +
      `sections` dict) exactly like every sibling `*Config` — `wilson_z`, three per-probe
      tolerances, `min_pairs`, all validated in `__post_init__` raising `ConfigError`.
- [x] Reuse `golden.py`'s hash splitter and `evaluate_on_split` held-out discipline.
      **Scope clarification**: does not apply to these three probe functions directly — none of
      order-flip/verbosity/self-preference fits a parameter, so there is nothing to hold out
      (unlike the existing numeric `Calibrator`, which `evaluate_on_split` fits on one partition
      and evaluates on another). `_bucket`/`split`/`evaluate_on_split` remain fully available
      and will be reused in Group 2/3 if corpus sampling or report-authoring needs a
      deterministic split; revisit this note there rather than forcing a fit-step these probes
      don't have.
      Verified: full `agent-core` suite green (`pytest`, 98.65% coverage/floor 95%,
      `mypy --strict` clean, `ruff` clean), `public_surface_baseline.json` regenerated
      (purely additive: 7 new names). Tests: `agent-core/tests/test_judge_calibration.py`
      (20 cases) + `test_config.py` (7 new `ProbeConfig` cases).

## 2. Corpus type — `agent_core` (unprotected)
- [x] Add a pairwise calibration item type (not `GoldenItem`, which is binary-label and has no pair).
      New `agent_core/pairwise.py`: `PairwiseItem` (`item_id, prompt, answer_a, answer_b,
      family_a, family_b, expected: "a"|"b"|"tie"|None, domain, source, canary_kind, meta`) +
      `PairwiseSet` (duplicate-id rejection, order-independent equality, deterministic JSONL
      round-trip) — mirrors `golden.py`'s `GoldenItem`/`GoldenSet` container conventions exactly,
      as a sibling module (not added to `golden.py` itself, since neither type generalises the
      other).
- [x] Add canaries: known-equal, clearly-better, clearly-worse.
      `PairwiseItem.canary_kind: "known_equal"|"clearly_better"|"clearly_worse"|None`, with
      cross-field validation in `__post_init__`: a `known_equal` canary must have
      `expected="tie"`; a `clearly_better`/`clearly_worse` canary must have `expected` in
      `("a","b")` — an internally-inconsistent canary is a corpus-authoring bug, caught at
      construction rather than silently scored wrong later. `PairwiseSet.canaries` property
      filters to tagged items.
      Verified: full `agent-core` suite green, `pairwise.py` 100% covered, `mypy --strict` and
      `ruff` clean, `public_surface_baseline.json` regenerated (purely additive: `PairwiseItem`,
      `PairwiseSet`). Tests: `agent-core/tests/test_pairwise.py` (19 cases).

## 3. Report — `agent_core` (unprotected)
- [x] Versioned `JudgeCalibrationReport` with agreement, κ, flip rate, verbosity delta,
      self-preference breakdown, CIs, sample size and power status.
      New `agent_core/judge_calibration_report.py` (a module separate from
      `calibration_report.py` — a different capability, agent-records proxy calibration vs.
      judge bias calibration — and from `judge_calibration.py`, which is the probe math this
      composes, not the report shape). `REPORT_SCHEMA_VERSION = "1.0.0"`, independent of
      `agent_core.version.SCHEMA_VERSION` (mirrors `eval_harness`'s `TRAJECTORY_SCHEMA_VERSION`
      precedent). Also added `golden.py::percent_agreement(r1, r2)` — Cohen's κ's raw `po`,
      exposed on its own since design.md lists "percent agreement" and "Cohen's κ" as two
      separate report fields.
      **Architectural finding, not pre-specified in tasks.md**: `agent_core` cannot call
      `flow_corpus.oracles.kappa_gate.validate_oracle` itself — `flow_corpus` sits *downstream*
      of `agent_core` in the dependency graph (`architecture.yaml`:
      `flow_corpus: [flow_protocol, agent_core]`), so an `agent_core -> flow_corpus` import
      would be a reverse edge and would breach the very airgap this proposal's own "Where the
      code goes" section explains. `JudgeCalibrationReport`'s agreement fields
      (`percent_agreement`, `kappa`, `n_codeterminate`, `directional_only`,
      `agreement_may_gate`) are therefore populated by the Group 4 caller
      (`behavioral_regression`, which already depends on both `agent_core` and `flow_corpus`)
      from its own `validate_oracle` call — this module defines the report's shape and its
      `may_gate` verdict, never how agreement itself gets computed. `build_judge_calibration_report`
      accepts every bias-probe and agreement value pre-computed; its only real work is the
      canary pass-rate check (comparing each canary's actual judge verdict against its
      `PairwiseItem.expected`), since nothing else compares those two.
- [x] Assert a judge with acceptable κ but a failing bias tolerance is not reported as validated.
      `JudgeCalibrationReport.may_gate` property: `agreement_may_gate and not failing_checks`;
      `failing_checks` names every currently-failing check (not just the first), satisfying
      spec.md's "the reason names the failing bias check." Canary results are diagnostic only,
      deliberately excluded from `may_gate` — spec.md's ADDED Requirements name agreement, power
      and the three bias tolerances as the gating conditions, not canaries; a canary failure
      helps a reviewer notice a judge has stopped discriminating (design.md) without itself
      being an automated gating condition nothing in spec.md asks for.
      Tests: `agent-core/tests/test_judge_calibration_report.py` (13 cases, covering good
      agreement + each bias check failing individually, `self_preference=None` correctly not
      counted as a failure, and canaries never affecting `may_gate`).
      Verified: full `agent-core` suite green, `judge_calibration_report.py` 100% covered,
      `mypy --strict` and `ruff` clean, `public_surface_baseline.json` regenerated.

## 4. Consumption — PR 2
- [x] Wire the report into `src/eval_harness/agent_core_adapter/`.
      New `require_report_to_gate(report, expected_artifact_id)` in
      `agent_core_adapter/__init__.py`, imported eagerly alongside `agent_core.protocols`
      (the module already hard-requires `agent-core`, so no new lazy-import seam is needed).
      Checks `report.artifact_id == expected_artifact_id` first — a stale or swapped-in
      report can't be substituted for the run a config actually named — then
      `report.may_gate`, raising with `report.failing_checks` named in the message when it
      does not authorise gating. Deliberately does **not** decide *how* a caller obtains the
      `JudgeCalibrationReport` (load from a file, a store, construct it in-process): no
      artifact-registry precedent exists in this codebase (Group 3's finding, unchanged).
      Tests: `tests/test_agent_core_adapter.py::TestRequireReportToGate` (3 cases: mismatched
      ID, failing bias check named in the error, and the passing path).
- [x] Wire into `behavioral_regression` alongside `validate_judge`.
      New `build_judge_calibration_report(...)` in `oracle.py`, exported from
      `behavioral_regression/__init__.py` next to `validate_judge` (both in `__all__`).
      Reuses `validate_judge`'s own `KappaReport` for `n_total`/`n_codeterminate`/`kappa`/
      `directional_only`/`agreement_may_gate`, and `agent_core.golden.percent_agreement`
      over the *same* codeterminate pairs (never re-derived) for the raw agreement rate —
      `0.0` when there are none, since `percent_agreement` itself rejects an empty sequence
      and an underpowered/`directional_only` report already can't gate regardless of that
      value. The three bias probes (order-flip, verbosity, self-preference) are accepted
      pre-computed, exactly like `agent_core.judge_calibration_report.
      build_judge_calibration_report`'s own contract — this function composes an existing
      agreement measurement with an existing probe pipeline, it does not run either itself.
      Tests: `behavioral-regression/tests/test_oracle.py` (4 new cases: length-mismatch,
      full composition incl. `may_gate`, percent-agreement scoped to codeterminate pairs
      only, and the zero-codeterminate-pairs edge case not crashing).
      Verified: `make check` (behavioral-regression) 100% coverage, `mypy --strict`/`ruff`
      clean, `tests/public_surface_baseline.json` regenerated (purely additive: one name).
- [x] `[P]` Require an explicit calibration artifact ID in gating configuration.
      New `JudgeCalibrationGateConfig` (`config/models.py`, sibling to `JudgeBudgetConfig`/
      `PhoenixConfig`) with a single required `calibration_artifact_id: str` field
      (`min_length=1`) — an opaque provenance string, like `ab_campaign.campaign_id`;
      `EvalConfig.judge_calibration: JudgeCalibrationGateConfig | None = None`.
      **Design correction, found by running the full suite, not by reasoning alone**: the
      first cut added an `EvalConfig`-level `model_validator` requiring the block whenever
      `judge is not None and gate.rules` — too coarse. Many existing configs legitimately
      configure a judge for measurement while gating only on programmatic scores, and the
      blanket check broke roughly a dozen unrelated passing tests. Config models have no
      dependency on the scorer registry (by design — they're pure data), so they cannot see
      a scorer's real, resolved name or `uses_judge()`; guessing from raw `ComponentSpec`
      dicts would mean duplicating every scorer type's `default_name`/child-composition
      logic in a module that shouldn't own it. Moved the actual check to
      `eval_harness.gating.require_calibration_for_judge_gating(config, scorers)` — called
      from `cli.py` right after `EvalEngine.from_config` (before `engine.run()`), where the
      *real*, constructed `Scorer` instances (and their real `.name`/`.uses_judge()`, via the
      same `_uses_judge()` helper pattern as `engine.py`) are already available. It only
      raises when a `gate.rules[].score` actually names a judge-backed scorer with no
      `judge_calibration` block — precise, not guessed.
      `config/eval.example.yaml` needed a `judge_calibration` block added (its own
      `gate.rules` names `helpfulness`, the `llm_judge` scorer) — another real, disclosed
      consequence of the new check, not a test-only fixture fix.
      Tests: `tests/test_config.py` (3 cases: absent by default, empty/missing ID rejected,
      named ID accepted); `tests/test_matrix_eval_tools.py::TestJudgeCalibrationGating` (5
      cases: raises when targeted without an ID, passes when named, and three "does not
      apply" cases — untargeted judge, empty gate, no gate at all).
- [x] `[P]` Assert an uncalibrated or biased judge cannot gate.
      Covered jointly by the two items above: `require_calibration_for_judge_gating` blocks
      an *unnamed* calibration at config/engine-construction time; `require_report_to_gate`
      blocks a named-but-failing (`may_gate is False`) or mismatched-ID calibration once a
      real `JudgeCalibrationReport` is in hand, naming every failing check in the error.
- [x] `[P]` Assert programmatic scorers are ordered ahead of judges.
      `Scorer.uses_judge()` (`core/interfaces.py`) — a plain method, not a `@property`, for the
      same `runtime_checkable`-Protocol reason as `TargetRunner.is_deterministic`. Defaults
      `False`; `CompositeScorer` delegates to its children, `LLMJudgeScorer` returns `True`.
      `EvalEngine.__init__` stable-sorts `self.scorers` on it, so judge-backed scorers always run
      after every programmatic one without disturbing relative order within each group.
      `_run_one`'s loop then skips a judge scorer entirely — no `ScoreResult` is recorded — once
      a programmatic scorer has already failed the item, satisfying spec.md's literal "the
      judge's verdict cannot convert that item into a pass."
      **Real bug found and fixed by running the full suite, not just new tests**: the first
      implementation recorded a synthetic `value=0.0, passed=None` placeholder for a skipped
      judge, mirroring `AutoevalsScorer`'s existing `on_skip` convention. That convention is
      opt-in and rare (a provider genuinely returning no score); this skip fires on any ordinary
      failing programmatic scorer and is common. The synthetic 0.0 silently dragged down that
      judge's aggregate `mean` for every downstream `mean`-based gate — caught concretely by
      `config/eval.example.yaml`'s own CLI smoke test flipping from PASS to FAIL with no real
      quality regression — and would have equally corrupted `reliability.py`'s per-scorer
      quantiles/attempt-counts (`attempts = len(pairs)` counts only entries actually present).
      Fixed by not appending anything at all for a skipped judge, so the item is excluded from
      that scorer's aggregate the same way a sampled-out item is excluded from the whole run —
      distinct from the adjacent genuine-error branch, whose `value=0.0, passed=False` is a real
      outcome and rightly still counts.
      **Second gap, also found by the full suite**: a duck-typed scorer that predates
      `uses_judge()` and never defines it crashed with `AttributeError` at the `sorted(...)` call
      site. Fixed with a defensive `_uses_judge()` module-level helper
      (`getattr(scorer, "uses_judge", None)`, `callable()`-guarded) used at every call site.
      **Third gap**: a judge-backed scorer's own exception must not itself trip the
      skip-later-judges guard — that guard exists only for a *programmatic* scorer having failed,
      not for a judge failing to run at all. Covered by a dedicated test (two judge-backed
      scorers, the first raises) after the full-suite run showed this branch uncovered.
      Tests: `tests/test_engine.py` (`test_engine_end_to_end_aggregate` re-asserted for the new
      skip semantics, `test_engine_writes_scores_to_langfuse` recount, new
      `test_a_judge_scorer_error_does_not_skip_a_later_judge_scorer`);
      `tests/test_matrix_eval_tools.py`'s `TestM4Interface.test_scorer_protocol_duck_typing`
      fixture updated with a trivial `uses_judge` override to keep satisfying the now-tightened
      structural `isinstance()` check.
      Verified: full root suite green (`python -m pytest tests/ -q`), `./scripts/quality-gate.sh
      all` PASS (98.22% coverage, floor 96%), `ruff` and `mypy` clean on every touched file.

## 5. Governance — PR 3
- [x] `[P]` Claim the next free F-ID; add an executable proof.
      F-057 (F-056 claimed first by `add-repeat-reliability-metrics`, per the plan's landing
      order). New `scripts/validations/F_057.py`, 26 `_check()` calls across 5 helper functions
      (`main()` delegates to each — a single flat `main()` tripped ruff's `C901` cyclomatic-
      complexity budget, the same shape fix as every other multi-section proof script's
      *density*, just organised differently) covering: probe math (order-flip, verbosity,
      self-preference, including a genuinely uninformative pair correctly excluded); the
      pairwise corpus's canary cross-validation and dedup; `JudgeCalibrationReport.may_gate`/
      `failing_checks`; `build_judge_calibration_report`'s canary pass rate and empty-canary
      rejection; the engine's scorer ordering and judge-skip (plus the duck-typed-scorer
      fallback, `# type: ignore[list-item]`'d at the two call sites that deliberately pass a
      non-conforming scorer to prove the runtime path a static check can't model);
      `JudgeCalibrationGateConfig`; both `require_calibration_for_judge_gating` and
      `require_report_to_gate`; and `behavioral_regression.build_judge_calibration_report`'s
      composition. Verified passing standalone (`PYTHONPATH=src python
      scripts/validations/F_057.py`, exit 0) before wiring into `features.yaml`.
- [x] `[P]` Regenerate both `tests/*_baseline.json`.
      Both already regenerated in Group 4's commit (`agent-core/tests/public_surface_baseline.json`
      needed no change there — no new agent_core public name in this group;
      `behavioral-regression/tests/public_surface_baseline.json` gained
      `build_judge_calibration_report`; root `tests/public_surface_baseline.json` gained
      `require_report_to_gate` on `eval_harness.agent_core_adapter`). No further changes needed
      in Group 5 itself.
- [x] Verify `architecture.yaml` is **unchanged** — a diff here means the airgap was breached.
      Confirmed via `git diff origin/main -- architecture.yaml`: the only delta is the
      `add-repeat-reliability-metrics` `reliability` component (F-056, landed separately);
      nothing from this proposal touches it — matches design.md's "no new component edge"
      claim exactly, not just approximately.
- [x] CHANGELOG + documentation.
      New `### Added — judge bias calibration...` section at the top of `## [1.3.0-dev] —
      Unreleased` in `CHANGELOG.md` (newest-first, ahead of F-056's own section). Deleted the
      now-stale `FollowOn("extend-judge-calibration", ...)` entry from `tests/_matrix_coverage.py`
      (mirrors the F-056 `FollowOn` cleanup precedent — the note tracked a proposal that hadn't
      landed yet, not a permanent structural blind spot) and regenerated `docs/matrix-coverage.md`.

## 6. Verification
- [x] Full gate suite; `make check-agent-core` at its own floor.
      Root `./scripts/quality-gate.sh all` (98%+ coverage, floor 96%), `agent-core`'s own
      `make check` (98.71% coverage, floor 95%, 855 passed), `behavioral-regression`'s own
      `make check` (100% coverage, floor 95%), `python scripts/validate.py --tier fast
      --strict` (55/55 features including F-057), `python tests/test_matrix_coverage.py
      --check` (fresh) — all green.
- [x] End-to-end: swapping answer order exposes a biased judge; an uncalibrated judge cannot gate.
      New `agent-core/tests/test_judge_calibration_end_to_end.py` (3 tests), mirroring
      `add-repeat-reliability-metrics`' own M8-pipeline precedent: a synthetic
      "always prefers whichever candidate is shown first" judge is actually graded in both
      answer orders (not hand-typed verdict strings) — its own collected verdicts feed
      `order_flip_rate`, which reports `flip_rate=1.0`/`passes=False`; that *measured* result
      then feeds `build_judge_calibration_report`, whose `may_gate` is `False` with
      `order_flip` named in `failing_checks` even though `percent_agreement`/`kappa` are
      deliberately set high — proving agreement alone cannot rescue a biased judge. A third
      test covers spec.md's sibling "underpowered" scenario (`directional_only=True` ->
      `may_gate=False`, `agreement_or_power` named), independent of any bias probe passing.

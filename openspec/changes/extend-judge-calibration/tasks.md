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
- [ ] Wire the report into `src/eval_harness/agent_core_adapter/`.
- [ ] Wire into `behavioral_regression` alongside `validate_judge`.
- [ ] `[P]` Require an explicit calibration artifact ID in gating configuration.
- [ ] `[P]` Assert an uncalibrated or biased judge cannot gate.
- [ ] `[P]` Assert programmatic scorers are ordered ahead of judges.

## 5. Governance — PR 3
- [ ] `[P]` Claim the next free F-ID; add an executable proof.
- [ ] `[P]` Regenerate both `tests/*_baseline.json`.
- [ ] Verify `architecture.yaml` is **unchanged** — a diff here means the airgap was breached.
- [ ] CHANGELOG + documentation.

## 6. Verification
- [ ] Full gate suite; `make check-agent-core` at its own floor.
- [ ] End-to-end: swapping answer order exposes a biased judge; an uncalibrated judge cannot gate.

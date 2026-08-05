# Tasks: extend-judge-calibration

`[P]` = protected path. Coverage floors: `agent-core` **95%**, root `eval_harness` **96%**.

## 1. Probe math — `agent_core` (unprotected)
- [ ] Add paired-order transformation and order-flip rate.
- [ ] Add controlled verbosity transformation and preference delta.
- [ ] Add judge-family metadata and self-preference breakdown.
- [ ] Frozen dataclass config; no YAML knobs, no numeric literals at call sites.
- [ ] Reuse `golden.py`'s hash splitter and `evaluate_on_split` held-out discipline.

## 2. Corpus type — `agent_core` (unprotected)
- [ ] Add a pairwise calibration item type (not `GoldenItem`, which is binary-label and has no pair).
- [ ] Add canaries: known-equal, clearly-better, clearly-worse.

## 3. Report — `agent_core` (unprotected)
- [ ] Versioned `JudgeCalibrationReport` with agreement, κ, flip rate, verbosity delta,
      self-preference breakdown, CIs, sample size and power status.
- [ ] Assert a judge with acceptable κ but a failing bias tolerance is not reported as validated.

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

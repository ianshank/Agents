# 0012 — A/B eval campaigns with statistical significance (additive, opt-in)

- Status: **Accepted.** Additive, opt-in; the single-run path is untouched.
- Date: 2026-06-30
- Related: F-024 (multi-model comparison), ADR 0006 (behavioral-regression honesty),
  `src/eval_harness/campaign.py`, `agent_core.calibration.wilson_interval`.

## Context

Beyond a one-shot comparison (F-024), teams want a **persistent** A/B campaign: run two
arms repeatedly over time, accumulate results, and get a statistically honest verdict on
whether arm B differs from arm A — without over-claiming on thin data.

## Decision

1. **Config** (`config/models.py`): `ABCampaignConfig` — `campaign_id`, two arms (reusing the
   F-024 `ModelSpec`), the `score` to test, `wilson_z`, and a `min_sample` power floor. Arms
   must have distinct names. `EvalConfig.ab_campaign` is additive and optional, so
   `SCHEMA_VERSION` is unchanged.
2. **Persistence**: a purpose-shaped append-only JSONL `CampaignStore` (per-arm pass/total
   counts per run), built on the same pattern as agent_core's `OutcomeStore`. agent_core's
   `persistence` module is shape-specific to CycleState/Calibrator, so a small dedicated store
   is the correct reuse — not the serializer.
3. **Reuse, never reimplement**: significance uses `agent_core.calibration.wilson_interval`
   (the permitted `eval_harness → agent_core` edge); each arm runs through `EvalEngine` with
   only its target swapped, exactly like F-024's per-model runs.
4. **Honest decision** (`analyze`): either arm below `min_sample` → `cant_tell` (no claim);
   otherwise disjoint Wilson intervals → `a_better`/`b_better`, overlapping → `no_difference`.
   This mirrors the behavioral-regression convention (ADR 0006): never assert significance
   below power. Counts **accumulate across runs**, so a campaign reaches power over time.
5. **CLI**: `eval-harness campaign --config … --store … [--mode record|analyze] [--offline]
   [--html] [--json]`; `record` runs both arms once and appends counts, `analyze` reports the
   decision and writes a self-contained deterministic report.

## Consequences

- **Backwards compatible.** No schema bump; opt-in entry point; single-run path untouched.
- **No hard-coded values.** Arms, score, z, and the power floor are all config-driven.
- **Conservative by construction.** Non-overlapping Wilson CIs is a stricter bar than a raw
  proportion test, and `cant_tell` is a first-class outcome, so the campaign never reports a
  difference it cannot defend.
- **Tested offline.** `tests/test_campaign.py` (validation, store accumulation, all four
  decisions, accumulation-reaches-power, to_dict/to_html, CLI) and
  `scripts/validations/F_025.py` run with deterministic `echo` targets. ≥96% branch coverage;
  ruff + strict mypy clean; drift gate unaffected (campaign reuses agent_core via the
  permitted edge).

# 0011 — Multi-model comparison (additive, opt-in)

- Status: **Accepted.** Additive, opt-in; the single-run path is untouched.
- Date: 2026-06-30
- Related: F-018 (parallel execution), F-021 (HTML sink), F-024,
  `src/eval_harness/comparison.py`, `src/eval_harness/config/models.py`.

## Context

Teams want to run one dataset against several models/systems-under-test and see a
side-by-side comparison (which model scores best, by how much) rather than reading N
separate run reports. This must reuse the existing scoring/aggregation machinery exactly
(so a per-model number is identical to a standalone run) and must not change the single-run
path or the config schema version.

> **Prerequisite note (carried from the plan).** `targets/` ships only `EchoTarget` and
> `CallableTarget` today — there is no LLM/model-backed target. F-024 is therefore the
> comparison *orchestration + report* over the existing target abstraction; a real
> model-backed target is a separate, optional follow-up. The comparison is fully exercised
> offline with deterministic `echo` targets.

## Decision

1. **Config** (`config/models.py`): `ModelSpec` (name + `ComponentSpec` target) and
   `ComparisonConfig` (`models` ≥2 with unique names, optional `baseline`, optional `rank_by`,
   `rank_metric` ∈ {mean, pass_rate}). `EvalConfig.comparison` is an additive optional field —
   `SCHEMA_VERSION` is unchanged and old configs parse untouched.
2. **Orchestration** (`comparison.py`): `run_comparison` builds a per-model config by copying
   the base config and swapping only the `target` (and the run name), then runs each through
   `EvalEngine` — so dataset/scorers/judge/gate behaviour is identical across models and
   parallelism (F-018) still applies per run.
3. **Shared primitive**: `compare_metric(runs, score, metric, baseline)` returns per-model
   values, deltas vs the baseline, and a ranking (None values preserved and ranked last, never
   silently invented). This primitive is reused by the A/B campaign feature (F-025).
4. **Report**: `ComparisonResult.to_dict()` (JSON) and `to_html()` — a single self-contained,
   deterministic HTML table (inline CSS, HTML-escaped, no external assets), reusing the
   string-built rendering approach of the F-021 `html_file` sink.
5. **CLI**: `eval-harness compare --config … [--offline] [--html …] [--json …]` runs the
   comparison and prints the ranking; exits 2 when the config has no `comparison` block.

## Consequences

- **Backwards compatible.** No schema bump, no change to single-run `run`; comparison is a
  separate, opt-in entry point. Edits live in `targets`-adjacent additive code and do not trip
  the architecture-drift gate (no new component edges).
- **No hard-coded values.** Models, baseline, ranking score, and metric are all config-driven.
- **Tested offline.** `tests/test_comparison.py` (validation, ranking/deltas, None handling,
  to_dict/to_html determinism, CLI) and `scripts/validations/F_024.py` run with deterministic
  `echo` targets — no network. ≥96% branch coverage; ruff + strict mypy clean.

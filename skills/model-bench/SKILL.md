---
name: model-bench
description: Benchmark and A/B-test multiple LLMs or systems-under-test on one evaluation dataset. Use this whenever the user wants to compare models side by side, rank candidates by a score, run a multi-model comparison, set up a persistent A/B eval campaign, decide whether a new model is significantly better than a baseline, or produce a comparative HTML/JSON benchmark report.
validator_version: '2.0'
compatibility: python>=3.10, langfuse-eval-harness
version: 1.0.0
---

# model-bench

Benchmark several models on the same dataset and report which is best — end to end —
by reusing the eval-harness multi-model comparison (F-024) and A/B eval campaign (F-025)
features. This skill **orchestrates, it does not re-implement**: its runner forwards to the
already-tested `eval-harness compare` and `eval-harness campaign` CLI subcommands, which in
turn reuse `run_comparison`, `record_run`, and `analyze`. With the real model-backed target
(F-027) wired into your config, the same commands benchmark live models; the bundled fixtures
use deterministic `echo` targets so the skill's own evals run offline.

Two modes:

* **compare** — run one dataset/scorers against ≥2 named models and rank them, with per-metric
  deltas vs a baseline and a self-contained comparative report. One-shot.
* **campaign** — a persistent A/B test of two arms whose per-arm pass/total counts accumulate
  across runs in an append-only store; `analyze` decides via Wilson intervals and never claims
  significance below its power floor.

## 1. Preconditions (input contract)

Confirm before executing. If any fails, stop and report the exact missing requirement.

* `langfuse-eval-harness` is importable (`pip install -e .` from the repo root; add the
  provider extra — `[openai]`, `[bedrock]`, `[anthropic]` — only when benchmarking real models).
* An eval config YAML exists with the relevant block:
  * **compare**: a `comparison` block with ≥2 uniquely-named models (each a `{type, params}`
    target) and a shared `dataset` + `scorers`.
  * **campaign**: an `ab_campaign` block with two distinctly-named arms, the `score` to test,
    and a `min_sample` power floor.
* For real models, the provider credentials are present in the environment (never in the
  config — use `${VAR}` interpolation). The bundled fixtures need no credentials.

## 2. Procedure

### compare

```
python scripts/run.py compare --config <eval.yaml> [--offline] [--html OUT.html] [--json OUT.json]
```

Prints the ranking (`ranked by <score> (<metric>): A > B > C`). `--offline` uses an in-memory
Langfuse client; `--html`/`--json` write the comparative report.

### campaign

```
# Record one run (repeat over time to accumulate counts):
python scripts/run.py campaign --config <eval.yaml> --store <store.jsonl> --mode record [--offline]

# Analyze the accumulated store:
python scripts/run.py campaign --config <eval.yaml> --store <store.jsonl> --mode analyze [--offline] [--json OUT.json]
```

`record` appends per-arm pass/total counts to the JSONL store; `analyze` accumulates them and
prints a decision (`a_better` / `b_better` / `no_difference` / `cant_tell` below power).

## 3. Output contract

* `compare` exits 0 and prints the ranking; with `--json`/`--html` it writes a deterministic,
  self-contained report (no external assets).
* `campaign --mode record` exits 0 and appends one record per arm; `--mode analyze` exits 0 and
  prints the decision and delta.
* A config missing the required block exits 2 with a clear message; a missing harness install
  exits 1.

## 4. No hard-coded values

Models, endpoints, datasets, the ranking score/metric, and campaign power floor all come from
the config; credentials come from the environment via `${VAR}` interpolation. Nothing about a
specific model or endpoint is baked into this skill.

## 5. Validation

```
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

The behavioral evals drive `compare` and a `record` → `analyze` campaign over the bundled
`echo`-target fixtures — fully offline and deterministic.

## 6. References

* `references/usage.md` — config block shapes and worked examples.

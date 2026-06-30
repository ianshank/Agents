# model-bench — config shapes & worked examples

model-bench forwards to the eval-harness `compare` and `campaign` CLI subcommands. The
config is a standard `EvalConfig` YAML with one extra block.

## compare (`comparison` block, F-024)

```yaml
schema_version: "1.0"
run: { name: my-bench, seed: 7 }
dataset:
  type: inline
  params:
    items:
      - { id: "1", inputs: { prompt: "2+2?" }, expected: "4" }
target: { type: echo, params: {} }      # shared default; overridden per model
scorers:
  - { type: exact_match, params: {} }
comparison:
  baseline: gpt                          # a model name; defines delta reference
  rank_by: exact_match                   # optional; defaults to first aggregate score
  rank_metric: mean                      # mean | pass_rate
  models:
    - name: gpt
      target: { type: model, params: { provider: openai, model: "${EVAL_MODEL}" } }
    - name: claude
      target: { type: model, params: { provider: anthropic, model: "${CLAUDE_MODEL}" } }
```

Run: `python scripts/run.py compare --config eval.yaml --html report.html`

`models` needs ≥2 unique names; `baseline` must be one of them. Each model swaps only the
`target`, so the dataset / scorers / judge are identical across models (per-model numbers match
a standalone run).

## campaign (`ab_campaign` block, F-025)

```yaml
ab_campaign:
  campaign_id: gpt-vs-claude
  arm_a: { name: gpt,    target: { type: model, params: { provider: openai,    model: "${EVAL_MODEL}" } } }
  arm_b: { name: claude, target: { type: model, params: { provider: anthropic, model: "${CLAUDE_MODEL}" } } }
  score: exact_match        # the scorer name whose pass-rate is A/B-tested
  wilson_z: 1.96            # optional CI z
  min_sample: 30            # power floor; below this, analyze returns cant_tell
```

Record repeatedly, then analyze:

```
python scripts/run.py campaign --config eval.yaml --store store.jsonl --mode record
python scripts/run.py campaign --config eval.yaml --store store.jsonl --mode analyze --json out.json
```

Counts accumulate across `record` runs, so a campaign reaches statistical power over time.
`analyze` decides via `agent_core` Wilson intervals: `cant_tell` below power, `a_better` /
`b_better` only when powered and the intervals separate, else `no_difference`.

## Offline / real models

The bundled fixtures (`evals/fixtures/`) use `echo` targets and run fully offline. Swap a
target to `{ type: model, params: {...} }` (F-027) to benchmark a real model; credentials are
read from the environment via `${VAR}` interpolation, never embedded in the config.

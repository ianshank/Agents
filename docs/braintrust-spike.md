# BrainTrust — experiment-export spike (reversible)

A thin, **additive, reversible** integration of [BrainTrust](https://www.braintrust.dev/)
behind the same narrow, SDK-optional seam the harness already uses for Langfuse and Phoenix.
It lets eval runs push results into BrainTrust **experiments** and run BrainTrust's
`autoevals` scorers — alongside the existing backends, not instead of them.

BrainTrust is **off by default** and **imported lazily** — nothing changes for existing
runs, `SCHEMA_VERSION` is unchanged, and the offline test suite needs no `braintrust` package
installed (the sink degrades to a no-op).

## What it adds

| File | Purpose |
|------|---------|
| `src/eval_harness/braintrust_client/__init__.py` | The seam: `BrainTrustClient` ABC / `NullBrainTrustClient` / injected-handle `SDKBrainTrustClient` + `build_client(enabled=…)` (export); `fetch_dataset_items(...)` (Phase 2 dataset read). Mirrors `phoenix_client`. |
| `src/eval_harness/sinks/__init__.py` | `@SINKS.register("braintrust") BrainTrustSink` — logs each item to a BrainTrust experiment; self-constructs its client, so **no engine wiring**. |
| `src/eval_harness/scorers/__init__.py` | `@SCORERS.register("autoevals") AutoevalsScorer` — bridges the `autoevals` scorer library into the `Scorer` contract (heuristic + LLM/Embedding). |
| `src/eval_harness/datasets/__init__.py` | `@DATASETS.register("braintrust") BrainTrustDataset` (Phase 2) — pulls a dataset via `init_dataset`; self-wiring, **fail-fast** when the SDK is absent (a dataset is essential input, not optional telemetry). |
| `pyproject.toml` | Optional `braintrust` / `autoevals` extras. `braintrust` is kept out of `dev`/CI; `autoevals` is installed in CI (offline-safe heuristics). |
| `architecture.yaml` / `architecture.mmd` | New `braintrust_client` component + the `sinks → braintrust_client` and `datasets → braintrust_client` edges. |

### Why the native `experiment.log` write-path (not the `Eval()` framework, not OTLP)

The harness runs the model and computes scores itself, then **pushes** results — so it uses
BrainTrust's lower-level `experiment.log({input, output, expected, scores={name: 0..1},
metadata})`, **not** the headline `Eval(name, data=, task=, scores=[…])` framework (which
iterates a dataset and runs the task for you). Scores are floats in `[0, 1]` — exactly the
harness `ScoreResult.value` range. Unlike the per-*score* Phoenix/Langfuse sinks, this is
per-*item*: one row carries the whole item plus a `{name: value}` scores dict.

BrainTrust also accepts OTLP spans (an alternative Phoenix-style export), but the native
`experiment.log` path is the narrowest, best-documented, most-stable surface (no `otel` extra,
no version-sensitive span-attribute convention), so it is the default here.

## Configuration (no hardcoded values)

Credentials come from the **environment**, read by the SDK itself — never from config or
source:

| Env var | Meaning |
|---------|---------|
| `BRAINTRUST_API_KEY` | Your BrainTrust API key (sent as `Authorization: Bearer …`). |
| `BRAINTRUST_API_URL` | Optional; overrides the default `https://api.braintrust.dev` for self-hosted stacks. |

```yaml
# eval config — read a BrainTrust dataset, run an autoevals scorer, export back to BrainTrust
dataset:
  type: braintrust
  params: { project_name: my-eval-project, name: my-dataset }   # version: "..." optionally pins one
scorers:
  - type: autoevals
    params: { scorer: Levenshtein, name: edit_distance, threshold: 0.6 }
sinks:
  - type: braintrust
    params: { enabled: true, project_name: my-eval-project, min_value_to_log: 0.0 }
```

The experiment is named after the run id. The `autoevals` scorer's Heuristic family
(`Levenshtein`, `ExactMatch`, `NumericDiff`, `JSONDiff`) is pure-Python; LLM/Embedding
scorers (`Factuality`, `ClosedQA`, `EmbeddingSimilarity`, …) call a provider at runtime —
set the provider key (e.g. `OPENAI_API_KEY`) in the environment. **Note:** those direct LLM
calls run OUTSIDE the harness `judge_budget`/rate-limit guard, which only wraps the `Judge`
seam.

## Install & run (networked environment only)

```bash
pip install -e '.[braintrust,autoevals]'
export BRAINTRUST_API_KEY=<key>
eval-harness run --config config/eval.example.yaml   # scores appear in the BrainTrust experiment
```

## Concept mapping (harness ↔ BrainTrust)

| Harness | BrainTrust |
|---------|-----------|
| `RunResult` (a run) | one **experiment** (`init(project, experiment=run_id)`) |
| `ItemResult` (an item) | one `experiment.log(...)` row |
| `ScoreResult(name, value∈[0,1])` | `scores={name: value}`; `run_id`/`config_name` → `metadata` |
| `EvalItem(inputs, expected)` / `TargetOutput(output)` | `input=` / `expected=` / `output=` |
| `Scorer` | `autoevals` scorer class (`evaluator(output=, expected=, input=)` → `Score`) |
| `DatasetSource` | `init_dataset(project, name, version)` → iterate `{id, input, expected, metadata}` |

## Testing (offline-first)

The suite never imports the real `braintrust` (it isn't installed in the air-gapped job). The
SDK paths are exercised via **`sys.modules` injection** of a fake `braintrust` whose `init`
returns a recording experiment — the no-op / ImportError fallbacks run for real. The
`autoevals` bridge is tested against the **real** `autoevals` package (installed in CI) for its
Heuristic scorers, with fakes for skip/error/missing-package paths.

```bash
pytest tests/test_braintrust_client.py tests/test_braintrust_sink.py \
       tests/test_braintrust_scorer.py -q
```

## Version-sensitivity (both SDKs are pre-1.0)

`braintrust` (0.27.x) and `autoevals` (0.3.x) are pre-1.0, so this seam binds only to the
narrowest documented surface — `braintrust.init(project=, experiment=)` + `experiment.log(...)`
with named 0..1 scores; `autoevals` `Score.score`/`.name`/`.metadata` and the canonical scorer
class names (not back-compat aliases like `LevenshteinScorer`). Extras are pinned `<1`. Newer
modules (e.g. `framework2.py` prompt registration) and the OTLP span-attribute convention are
deliberately avoided.

## Rollback

Fully reversible with no data migration and no change to existing users: delete
`braintrust_client/`, the `BrainTrustSink` block, the `AutoevalsScorer` block, the two
`pyproject` extras, the `braintrust_client` component + edge in `architecture.yaml`/`.mmd`, and
the three test files. Core depends only on the ABCs; nothing else imports BrainTrust.

## Phase 2 status

**Shipped:**
- **Dataset source** (`@DATASETS.register("braintrust")`) — verified against the installed
  `braintrust` 0.27 SDK: `init_dataset(project, name, version)` returns a `Dataset` whose
  iteration yields `DatasetEvent` records (`id`, `input`, `expected`, `metadata`), mapped onto
  the harness record shape. Offline-tested via fake-`sys.modules` injection; a live path is
  covered by `tests/test_braintrust_live.py`.
- **LLM/Embedding `autoevals` scorers** — already supported by the Phase 1 `AutoevalsScorer`
  bridge (any `autoevals` class name + provider key from the env); a live `Factuality` test is
  in `tests/test_braintrust_live.py`.

**Still deferred — managed prompts.** BrainTrust's `load_prompt(project, slug, version)` →
`Prompt`, and `Prompt.build()` returns OpenAI-client kwargs (`{messages, model, …}`) — a
*chat-message* structure. The harness's managed-prompt seam (`PromptSourceConfig`, F-026) feeds
a single judge **system string**, so mapping a BrainTrust chat prompt onto it is lossy and
would touch two protected eval paths (`config/models.py` + `engine.py`) while overlapping the
existing Langfuse prompt registry. This needs a small design decision (how to collapse chat
messages to the judge system string, or whether to expose the full message array) before wiring
— tracked as a follow-up rather than forced in. A top-level `BrainTrustConfig` block (peer to
`PhoenixConfig`) would be introduced alongside it if shared config is needed; it is omitted so
far because the sink and dataset source are fully configured by their own component params.

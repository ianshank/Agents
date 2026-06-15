# langfuse-eval-harness

A dynamic, modular, backwards-compatible enterprise LLM evaluation harness with
first-class Langfuse integration. Everything that drives behaviour is config —
there are no hard-coded thresholds, model ids, paths, or seeds in the engine.

## Why it is shaped this way

| Requirement | How it is met |
|---|---|
| **No hard-coded values** | All behaviour comes from a validated config (`EvalConfig`). Defaults live on the schema and are overridable via `--set` or `${ENV_VAR:-default}` interpolation. |
| **Modular / dynamic** | Components (scorers, datasets, targets, sinks, judges) self-register in `Registry` objects and are built by name at runtime. Third parties add components via the `eval_harness.plugins` entry-point group — no edits to this package. |
| **Backwards compatible** | Configs carry a `schema_version`; the migration chain upgrades old configs to the current schema on load. Registry **aliases** keep renamed component names resolving. Component contracts are abstract base classes, so implementations can evolve. |
| **Test coverage** | Offline pytest suite (no network/SDK) at ~96% line coverage, using a deterministic mock judge and an in-memory Langfuse client. |
| **Langfuse integration** | Hidden behind a narrow `LangfuseClient` interface with a `NullLangfuseClient` (tests/offline) and a guarded `SDKLangfuseClient` (production). |

## Install

```bash
pip install -e .            # core (pydantic, pyyaml)
pip install -e '.[langfuse]' # add the real Langfuse SDK
pip install -e '.[bedrock]'  # add boto3 for the Bedrock judge
pip install -e '.[dev]'      # pytest + coverage
```

## Run

```bash
eval-harness list-plugins
eval-harness run --config config/eval.example.yaml --offline
eval-harness run --config config/eval.example.yaml --set run.sample_rate=0.1
```

The process exits non-zero when the quality gate fails, so it drops directly
into a CI step.

## Extend (no core changes)

```python
from eval_harness.core.interfaces import Scorer
from eval_harness.core.types import ScoreResult
from eval_harness.plugins import SCORERS

@SCORERS.register("length_ok", aliases=("len",))
class LengthScorer(Scorer):
    default_name = "length_ok"
    def __init__(self, name=None, max_chars=280):
        super().__init__(name)
        self.max_chars = max_chars
    def score(self, item, output, ctx):
        ok = len(str(output.output)) <= self.max_chars
        return ScoreResult(self.name, 1.0 if ok else 0.0, ok)
```

Reference it from config: `{type: length_ok, params: {max_chars: 140}}`.

## Test

```bash
pytest --cov=eval_harness --cov-report=term-missing
```

## Layout

```
src/eval_harness/
  config/        versioned models, migrations, env-interpolating loader
  core/          types, interfaces, generic registry
  scorers/       exact_match, regex_match, contains, json_keys, llm_judge
  datasets/      inline, jsonl, langfuse
  targets/       echo, callable (dynamic import)
  sinks/         console, json_file, langfuse
  judges/        mock (deterministic), bedrock (guarded)
  langfuse_client/  interface + null + SDK adapter
  gating/        config-driven quality gate
  engine.py      orchestration
  cli.py         entry point
```

See `docs/c4_architecture.svg` for the C4 context/container/component views.

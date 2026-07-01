# Arize Phoenix — observability spike (reversible)

A thin, **additive, reversible** integration of [Arize Phoenix](https://arize.com/phoenix/)
behind the same narrow, SDK-optional seam pattern the harness already uses for Langfuse.
It lets us **run Phoenix alongside Langfuse and compare** before committing to either.

Phoenix is **off by default** and **imported lazily** — nothing changes for existing runs,
and the offline test suite needs no Phoenix packages installed.

## What it adds

| File | Purpose |
|------|---------|
| `src/eval_harness/phoenix_client/__init__.py` | The seam: `configure_tracing()` + `phoenix_observe()` (tracing) and `PhoenixScoreClient` / `NullPhoenixScoreClient` / `SDKPhoenixScoreClient` + `build_score_client()` (score export). Mirrors `langfuse_client`. |
| `src/eval_harness/sinks/__init__.py` | `@SINKS.register("phoenix") PhoenixSink` — logs eval scores; self-constructs its client, so **no engine wiring**. |
| `src/eval_harness/config/models.py` | `PhoenixConfig` (optional `EvalConfig.phoenix` block; `SCHEMA_VERSION` unchanged). |
| `src/eval_harness/cli.py` | One gated `configure_tracing(config.phoenix)` call in `run`. |
| `pyproject.toml` | Optional `phoenix` / `phoenix-evals` extras (kept out of `dev`). |

### Two deliberately-separate seams
- **Tracing** rides on `arize-phoenix-otel`'s `register(auto_instrument=True)`. Auto-instrumentation only
  emits spans for providers whose OpenInference instrumentor is installed — hence the `phoenix` extra ships
  the OpenAI/Anthropic/Bedrock instrumentors, matching the harness's judge targets.
- **Score export** emits each eval score as an **OpenTelemetry span** with `eval.*` attributes, using only the
  stable `arize-phoenix-otel` surface — so it needs no version-pinned `arize-phoenix-client` API.

## Configuration (no hardcoded values)

Endpoint and key come from the **environment**, never from config or source:

| Env var | Meaning |
|---------|---------|
| `PHOENIX_COLLECTOR_ENDPOINT` | OTLP collector URL of your self-hosted Phoenix (e.g. `http://localhost:6006`). Omit to use the SDK default. |
| `PHOENIX_API_KEY` | Optional; only if your Phoenix has auth enabled. |

```yaml
# eval config — enable tracing + score export
phoenix:
  enabled: true
  project_name: my-eval-project   # overridable; endpoint/key come from env
sinks:
  - type: phoenix
    params: { enabled: true, min_value_to_log: 0.0 }
```

## Install & run (networked environment only)

> **Air-gap note:** PyPI is TLS-blocked in some CI here, so `arize-phoenix-*` cannot be installed there.
> The offline suite is unaffected (the seam degrades to a no-op). Live tracing requires a networked runner.

```bash
pip install -e '.[phoenix]'            # tracing + OpenInference instrumentors

# Self-hosted Phoenix as a separate process (pin the tag — do not use :latest):
PHOENIX_IMAGE="arizephoenix/phoenix:<pin-a-release>"   # see hub.docker.com/r/arizephoenix/phoenix/tags
docker run -p 6006:6006 "$PHOENIX_IMAGE"               # SQLite by default; Postgres via PHOENIX_SQL_DATABASE_URL

export PHOENIX_COLLECTOR_ENDPOINT="http://localhost:6006"
eval-harness run --config config/eval.example.yaml     # traces + scores appear in Phoenix at :6006
```

## ROI — demonstrated in code vs documented-for-live

Because Langfuse already covers tracing + evals here, ROI is **non-redundant marginal value**.

| Dimension | Status in this spike | Marginal ROI vs existing Langfuse |
|-----------|----------------------|-----------------------------------|
| **1. Trace debugging / visibility** (OpenInference) | **Demonstrated in code** (`configure_tracing`, auto-instrument, span export) | **Highest** — OTel-native, vendor-neutral, runs *alongside* Langfuse for a true A/B. |
| **2. Eval quality** (`arize-phoenix-evals`) | **Documented** (`phoenix-evals` extra; validate live) | High — pre-built hallucination/QA/toxicity judges; complements `judges/`. |
| **3. Experiments & datasets** (`run_experiment`) | **Documented** (not exercised) | Medium — overlaps existing `behavioral-regression` / `flow-corpus`. |
| **4. OTel standardization** across services | **Foundation laid** (OTLP export) | Medium (long-term) — achieved incrementally via #1. |

**Recommendation:** adopt **#1 (self-hosted OpenInference tracing)** as the entry point — highest ROI, lowest
risk, and because it's OTLP it coexists with Langfuse so the spike doubles as the comparison. Expand to #2
(`arize-phoenix-evals`) only after the live dependency resolution below is confirmed.

## Before expanding to evals (networked, one-time)

`arize-phoenix-evals` pulls `pandas`/`numpy`; the repo pins `pyarrow>=14,<20`. Resolve the interaction on a
networked env **before** writing evaluator code:

```bash
pip install '.[phoenix-evals,parquet]' --dry-run    # confirm numpy/pyarrow resolve; record the ranges
```

## Testing (offline-first)

The suite never imports the real `phoenix` (it isn't installable in the air-gapped job). The SDK paths are
exercised via **`sys.modules` injection** of a fake `phoenix.otel` — *not* `@patch("phoenix.otel.register")`,
which would raise `ModuleNotFoundError` at patch time. `phoenix_client` and the `PhoenixSink` are at **100%**
coverage offline; the no-op / ImportError fallbacks run for real.

```bash
pytest tests/test_phoenix_config.py tests/test_phoenix_tracing.py \
       tests/test_phoenix_sink.py tests/test_phoenix_cli.py -q
```

## Rollback

Fully reversible with no data migration and no change to existing Langfuse users: delete
`phoenix_client/`, the `PhoenixSink` block, the `PhoenixConfig` + `EvalConfig.phoenix` field, the one
`configure_tracing` call in `cli.py`, and the two `pyproject` extras. Core depends only on the ABCs;
nothing else imports Phoenix.

## If adopted → consolidation follow-up

Do **not** refactor Langfuse now. If Phoenix wins the comparison, extract a provider-neutral
`ObservabilityBackend` protocol (`trace()` + `record_scores()`) and make both Langfuse and Phoenix
implement it — turning today's intentional, low-risk duplication into a shared abstraction.

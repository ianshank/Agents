# Quickstart — Your First Eval in 5 Minutes

> **Prerequisites:** Python ≥3.11 and `pip`. No API keys needed for this
> walkthrough — everything runs offline.

---

## 1. Install

```bash
# Clone and install (editable, dev extras)
git clone https://github.com/ianshank/Agents.git
cd Agents
pip install -e ".[dev]"
```

Verify:

```bash
eval-harness --version
# → 1.3.0.dev0
```

---

## 2. Run the Bundled Example

The repo ships with a ready-to-run example config:

```bash
eval-harness run --config config/eval.example.yaml --offline
```

**What just happened:**

1. Two inline dataset items were loaded (`q1` and `q2`)
2. The `echo` target echoed back each question as the "LLM output"
3. Two scorers ran on each output:
   - `contains` — checked if the output mentions "reset"
   - `llm_judge` — used the `mock` judge (returns 0.9, except 0.4 for "cancel")
4. The quality gate evaluated: `helpfulness mean ≥ 0.5` and `mentions_reset pass_rate ≥ 0.5`
5. Results were printed to console and saved to `./out/results.json`

---

## 3. Create Your Own Config

Create `my_eval.yaml`:

```yaml
schema_version: "1.0"

run:
  name: "my-first-eval"
  seed: 42

dataset:
  type: inline
  params:
    items:
      - id: greeting
        inputs: { prompt: "Say hello" }
        expected: "Hello! How can I help you today?"
      - id: farewell
        inputs: { prompt: "Say goodbye" }
        expected: "Goodbye! Have a great day."

target:
  type: echo
  params:
    output_key: prompt

scorers:
  - type: contains
    params: { name: has_hello, substring: "hello" }
  - type: exact_match
    params: { name: exact }

sinks:
  - type: console
    params: { verbose: true }
  - type: json_file
    params: { path: "./out/my_results.json" }

gate:
  rules:
    - { score: has_hello, metric: pass_rate, min: 0.5 }
```

Run it:

```bash
eval-harness run --config my_eval.yaml --offline
```

---

## 4. Use a JSONL Dataset

Instead of inline items, point to a file:

```yaml
dataset:
  type: jsonl
  params:
    path: "path/to/your/dataset.jsonl"
```

Each line must be a JSON object with `id`, `inputs`, and optionally `expected`:

```jsonl
{"id": "s1", "inputs": {"text": "the cat sat"}, "expected": "summary: the cat sat"}
{"id": "s2", "inputs": {"text": "rockets are loud"}, "expected": "summary: rockets are loud"}
```

---

## 5. Connect a Real LLM Judge

Replace the `mock` judge with a real OpenAI-compatible endpoint:

```yaml
judge:
  type: openai
  params:
    model: "gpt-4o-mini"
    # Reads OPENAI_API_KEY from environment
```

Install the optional dependency:

```bash
pip install -e ".[openai]"
```

Set your key:

```bash
export OPENAI_API_KEY="sk-..."
```

Drop the `--offline` flag:

```bash
eval-harness run --config my_eval.yaml
```

---

## 6. Connect to Langfuse

Add Langfuse credentials to your environment:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"  # or your self-hosted URL
```

Install the optional dependency:

```bash
pip install -e ".[langfuse]"
```

Run without `--offline`:

```bash
eval-harness run --config my_eval.yaml
```

Scores and traces will appear in your Langfuse dashboard.

---

## 7. Multi-Model Comparison

Compare two models side-by-side with an HTML report:

```yaml
schema_version: "1.0"

run:
  name: "model-comparison"
  seed: 42

dataset:
  type: inline
  params:
    items:
      - id: q1
        inputs: { question: "What is Python?" }
        expected: "A programming language."

comparison:
  targets:
    - name: "gpt-4o-mini"
      type: model
      params: { model: "gpt-4o-mini", provider: "openai" }
    - name: "echo-baseline"
      type: echo
      params: { output_key: question }

scorers:
  - type: contains
    params: { name: mentions_python, substring: "Python" }

judge:
  type: openai
  params: { model: "gpt-4o-mini" }

sinks:
  - type: console
```

```bash
eval-harness compare --config comparison_eval.yaml
```

---

## What's Next?

| Goal | Guide |
|---|---|
| Understand the architecture | [docs/c4_architecture.md](c4_architecture.md) |
| Add custom scorers/judges/sinks | [README.md § Extend](../README.md#extend-no-core-changes) |
| Run evaluations in CI | [README.md § CI Integration](../README.md#ci-integration) |
| Configure quality gates | [config/README.md](../config/README.md) |
| Browse available skills | [skills/README.md](../skills/README.md) |
| Understand the 5-package monorepo | [CHARTER.md](CHARTER.md) |
| Read the full changelog | [CHANGELOG.md](../CHANGELOG.md) |

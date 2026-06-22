# langfuse-eval-harness

A dynamic, modular, backwards-compatible enterprise LLM evaluation harness with
first-class Langfuse integration, Snyk dependency scanning, and a pluggable skill
framework.

## Architecture

See [C4 Architecture Diagrams](docs/c4_architecture.md) for context, container,
component, and data-flow views.

| Requirement | How it is met |
|---|---|
| **No hard-coded values** | All behaviour comes from a validated config (`EvalConfig`). Defaults live on the schema and are overridable via `--set` or `${ENV_VAR:-default}` interpolation. Credentials are sourced from environment variables only. |
| **Modular / dynamic** | Components (scorers, datasets, targets, sinks, judges) self-register in `Registry` objects and are built by name at runtime. Third parties add components via the `eval_harness.plugins` entry-point group — no edits to this package. |
| **Backwards compatible** | Configs carry a `schema_version`; the migration chain upgrades old configs to the current schema on load. Registry **aliases** keep renamed component names resolving. Component contracts are abstract base classes, so implementations can evolve. |
| **Test coverage** | Offline pytest suite (no network/SDK) at ≥85% line coverage, using a deterministic mock judge and an in-memory Langfuse client. The quality-gate tooling has its own ≥85% coverage gate. |
| **Langfuse integration** | Hidden behind a narrow `LangfuseClient` interface with a `NullLangfuseClient` (tests/offline) and a guarded `SDKLangfuseClient` (production). |
| **Security** | Snyk monitors dependencies continuously. No credentials in source code. |
| **Eval integrity** | A regression gate blocks *net-new* lint/test failures vs the base, and a CODEOWNERS + label guard prevents silent weakening of evaluation-defining files. See [Quality Gates](#quality-gates). |

## Install

```bash
pip install -e .            # core (pydantic, pyyaml)
pip install -e '.[langfuse]' # add the real Langfuse SDK
pip install -e '.[openai]'   # add OpenAI + tenacity for judge
pip install -e '.[bedrock]'  # add boto3 for the Bedrock judge
pip install -e '.[anthropic]' # add anthropic for the Anthropic judge
pip install -e '.[data]'     # add pandas/pyarrow for CSV/Parquet datasets
pip install -e '.[dev]'      # pytest, coverage, ruff, mypy
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LANGFUSE_SECRET_KEY` | For Langfuse features | Langfuse secret key |
| `LANGFUSE_PUBLIC_KEY` | For Langfuse features | Langfuse public key |
| `LANGFUSE_BASE_URL` | For Langfuse features | Langfuse API endpoint (e.g. `https://us.cloud.langfuse.com`) |
| `NVIDIA_API_KEY` | For Nemotron judge | NVIDIA API key |
| `OPENAI_API_KEY` | For OpenAI judge | OpenAI API key |
| `ANTHROPIC_API_KEY` | For Anthropic judge | Anthropic API key |

Create a `.env` file from the template:
```bash
cp .env.example .env
# Edit .env with your credentials
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
# Full suite with coverage
pytest --cov=eval_harness --cov-report=term-missing

# Lint and type checks
ruff check src/ tests/
mypy src/eval_harness/
```

## Quality Gates

Because this is an **evaluation harness**, the cheapest way to make a check "pass" is to
weaken the evaluation itself (lower a gate threshold, swap to the `mock` judge, edit a
`verification:` clause). Two complementary gates make that hard:

```bash
# Regression gate — fails only on NET-NEW lint/test findings vs the base ref.
python scripts/regression_gate.py --base-ref origin/main --report-path regression_report.json
python scripts/regression_gate.py --mode warn      # annotate-only soak mode

# Eval-integrity guard — fails if evaluation-defining files change without approval.
python scripts/check_protected_changes.py --base-ref origin/main
```

- **Regression gate** (`F-006`) materialises an isolated `git worktree` baseline and runs
  `ruff` + the offline pytest suite in both trees, blocking only findings that are new
  relative to the base. It never runs live-judge / Langfuse evals.
- **Protected-path guard** (`F-007`) + `.github/CODEOWNERS` require a human-reviewed
  `eval-change-approved` label for any change under `features.yaml`, `config/`,
  `src/eval_harness/{gating,scorers,judges}/`, `scripts/validations/`, `tests/`, or
  `.github/`. The single source of truth is `scripts/eval_protected_paths.py`.
- **Auto-fix loop** (`F-008`) is intentionally **disabled** design-only scaffolding; see
  [`docs/decisions/0004-auto-fix-loop.md`](docs/decisions/0004-auto-fix-loop.md).

The regression gate and protected-path guard run in
`.github/workflows/quality-gates.yml`. The auto-fix loop (`F-008`) is disabled and is
**not** wired into CI.

## Security Scanning

```bash
# Run Snyk dependency scan
snyk test --file=requirements.txt --package-manager=pip --skip-unresolved

# Update Snyk dashboard
snyk monitor --file=requirements.txt --package-manager=pip --skip-unresolved
```

## Layout

```
src/eval_harness/
  config/          versioned models, migrations, env-interpolating loader
  core/            types, interfaces, generic registry
  scorers/         exact_match, regex_match, contains, json_keys, llm_judge
  datasets/        inline, jsonl, langfuse, csv, parquet
  targets/         echo, callable (dynamic import)
  sinks/           console, json_file, langfuse
  judges/          mock (deterministic), openai (Nemotron/GPT), bedrock, anthropic
  langfuse_client/ interface + null + SDK adapter
  gating/          config-driven quality gate
  engine.py        orchestration
  cli.py           entry point

scripts/
  validate.py             spec-driven project validation
  validate_skill.py       skill structural + behavioral validation
  select_next.py          feature priority selector
  regression_gate.py      net-new lint/test diff vs an isolated HEAD baseline
  eval_protected_paths.py single source of truth for protected eval-defining paths
  check_protected_changes.py  CI guard: flags protected changes lacking approval
  fix_loop.py             auto-fix loop scaffolding (DESIGN-ONLY, disabled)
  validations/            per-feature validation scripts (F_0NN.py)

skills/
  openai-judge/     skill: OpenAI-compatible LLM judge evaluation

docs/
  c4_architecture.md  C4 context/container/component diagrams
  decisions/          Architecture Decision Records (ADRs)
  SKILL_TEMPLATE.md   template for new skills
```

## CI Integration

```yaml
# GitHub Actions example
- name: Test
  run: pytest --cov=eval_harness --cov-report=term-missing --cov-fail-under=85

- name: Lint
  run: ruff check src/ tests/

- name: Type check
  run: mypy src/eval_harness/

- name: Security scan
  run: snyk test --file=requirements.txt --package-manager=pip --skip-unresolved
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

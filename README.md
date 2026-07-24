# langfuse-eval-harness

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Coverage](https://img.shields.io/badge/branch%20coverage-%E2%89%A595%25-brightgreen.svg)](#test)
[![CI](https://github.com/ianshank/Agents/actions/workflows/eval-harness-ci.yml/badge.svg)](https://github.com/ianshank/Agents/actions/workflows/eval-harness-ci.yml)

A dynamic, modular, backwards-compatible enterprise LLM evaluation harness with
first-class Langfuse integration, Snyk dependency scanning, and a pluggable skill
framework.


## Contents

- [Monorepo map](#monorepo-map)
- [Documentation](#documentation)
- [Architecture](#architecture)
- [Install](#install)
- [Environment Variables](#environment-variables)
- [Backends and integrations](#backends-and-integrations)
- [Run](#run)
- [Demo](#demo)
- [Extend (no core changes)](#extend-no-core-changes)
- [Test](#test)
- [Quality Gates](#quality-gates)
- [Security Scanning](#security-scanning)
- [Layout](#layout)
- [CI Integration](#ci-integration)
- [Changelog](#changelog)

## Monorepo map

A monorepo of five installable Python packages plus a skills marketplace and
operational tooling. Each package builds and tests **independently** with its own
coverage floor. Full package table and version gates: [AGENTS.md](AGENTS.md).

| Path | Package | Role |
|---|---|---|
| [`src/eval_harness/`](src/eval_harness/README.md) | `langfuse-eval-harness` | LLM evaluation harness (this package) |
| [`agent-core/`](agent-core/README.md) | `agent-core` | Deterministic control & calibration core |
| [`behavioral-regression/`](behavioral-regression/README.md) | `behavioral-regression` | Calibrated ship/hold/escalate regression gate |
| [`flow-corpus/`](flow-corpus/README.md) | `flow-corpus` | Calibration corpus of agentic flow variants |
| [`flow-protocol/`](flow-protocol/README.md) | `flow-protocol` | Versioned contract between corpus and harness |
| [`claude-foundation/`](claude-foundation/README.md) | `claude-foundation-tools` | Foundation Claude Code plugin tooling |
| [`skills/`](skills/README.md) | — | Vendored skills registered in `marketplace.yaml` |
| [`scripts/`](scripts/README.md) | — | Feature validators + CI guards |

## Documentation

- **[docs/](docs/README.md)** — the documentation index (architecture, ADRs, runbooks, spikes, baselines).
- **[AGENTS.md](AGENTS.md)** — orientation for coding agents and the root-documentation map.
- **[docs/CHARTER.md](docs/CHARTER.md)** — north-star scope & invariants.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** · **[GOVERNANCE.md](GOVERNANCE.md)** · **[SECURITY.md](SECURITY.md)** · **[SUPPORT.md](SUPPORT.md)** · **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)**
- Docs also render as a site: `pip install -e '.[docs]' && mkdocs serve` (see [mkdocs.yml](mkdocs.yml)).

## Architecture

Two artifacts with deliberately different edge semantics:

- [docs/c4_architecture.md](docs/c4_architecture.md) — hand-maintained C4
  context/container diagrams, narrative sub-component (L3) internals, and
  data-flow views. Edges there are **runtime/call relations** (who calls whom,
  over which protocol).
- [architecture.mmd](architecture.mmd) — the **generated import-edge component
  view**, derived deterministically from [architecture.yaml](architecture.yaml)
  (`python skills/architecture-drift-guard/scripts/mermaid_gen.py --manifest architecture.yaml -o architecture.mmd`)
  and drift-gated against the real import graph in CI.

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
pip install -e '.[braintrust]' # add the BrainTrust SDK for the braintrust sink
pip install -e '.[autoevals]'  # add the autoevals scorer library
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
| `BRAINTRUST_API_KEY` | For the braintrust sink | BrainTrust API key |
| `BRAINTRUST_API_URL` | Self-hosted BrainTrust | Overrides `https://api.braintrust.dev` |

Create a `.env` file from the template:
```bash
cp .env.example .env
# Edit .env with your credentials
```

## Backends and integrations

The harness talks to observability, dataset, and model backends through registry
components — `eval-harness list-plugins` prints the selectable names. Every external
SDK is **optional** and sits behind a reversible seam (a `Null*` double for
offline/tests, a guarded `SDK*` for production, built by a `build_*` factory) that
**fails safe to offline** when the SDK or credentials are absent, so the default
suite runs with zero network. Reversible-adoption pattern:
[`docs/phoenix-spike.md`](docs/phoenix-spike.md) and
[`docs/braintrust-spike.md`](docs/braintrust-spike.md); a live opt-in check runs in
[`.github/workflows/phoenix-live.yml`](.github/workflows/phoenix-live.yml).

| Backend | Dataset | Sink | Judge | Scorer | Client | Install extra | Status |
|---|---|---|---|---|---|---|---|
| **Langfuse** | `langfuse` | `langfuse` | — | — | `langfuse_client` (engine-injected) | `[langfuse]` | **Shipped — first-class** |
| **Phoenix** | — | `phoenix` | `phoenix_evals` | — | `phoenix_client` (OTLP tracing + score export) | `[phoenix]`, `[phoenix-evals]` | **Shipped — SDK-optional** |
| **BrainTrust** | `braintrust` | `braintrust` | — | `autoevals` | `braintrust_client` | `[braintrust]`, `[autoevals]` | **Shipped — SDK-optional** |
| **Local** | `inline`, `jsonl`, `csv`, `parquet` | `console`, `json_file`, `html_file` | — | — | — | core (`[parquet]` for parquet) | **Shipped** |
| **OpenAI-compatible** ¹ | — | — | `openai` | — | — | `[openai]` | **Shipped** |
| **Anthropic** | — | — | `anthropic` | — | — | `[anthropic]` | **Shipped** |
| **AWS Bedrock** | — | — | `bedrock` | — | — | `[bedrock]` | **Shipped** |
| **Opik** | — | — | — | — | — | — | **Under evaluation** ² |

¹ OpenAI, **NVIDIA Nemotron**, and a local **LM Studio** server are the *same* path —
the `openai` judge and the `model` (alias `llm`) target pointed at a different
`base_url` (`config/nemotron_eval.yaml`, `config/lm_studio_eval.yaml`), not separate
integrations.

² **Opik** has no code under `src/eval_harness/`; it is a *candidate* eval backend
probed alongside Langfuse in the isolated, unsigned
[`experiments/backend-validation/`](experiments/backend-validation/README.md) sandbox
(own gate; not in `make check-all`) — **not** a shipped integration.

The `budgeted` judge budget wraps any of the above judges with a per-run cost cap
(`agent_core_adapter`), applied by the engine when configured — it is not itself a
selectable judge. Per-backend credentials live in [`.env.example`](.env.example) (the
[Environment Variables](#environment-variables) table lists the common ones; Bedrock
uses the standard AWS credential chain). For the component **file layout**, see
[Layout](#layout).

## Run

```bash
eval-harness list-plugins
eval-harness run --config config/eval.example.yaml --offline
eval-harness run --config config/eval.example.yaml --set run.sample_rate=0.1
```

The process exits non-zero when the quality gate fails, so it drops directly
into a CI step.

## Demo

A repeatable, fully offline demo (zero credentials, deterministic) lives in
[`demo/`](demo/README.md). One command runs the whole story — pluggable harness,
a passing then CI-failing quality gate, multi-model comparison, and calibrated
ship/hold/escalate decisions:

```bash
PYTHONPATH=. bash demo/run_demo.sh
```

See [`demo/README.md`](demo/README.md) for the spoken runbook (per-beat commands,
expected output, and an engineer/leader narration) and `demo/deck.html` for a
self-contained visual walkthrough.

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

The whole gate is one deterministic, committed script (generated by the `quality-gate`
skill; regenerate with the `# regenerate:` command in its header):

```bash
./scripts/quality-gate.sh all        # lint + format-check + 3 per-path mypy runs
                                     # + pytest --cov=eval_harness (>=96)
                                     # + the F-031 scripts-coverage gate (hand extension)
make check                           # same thing, via the generated Makefile
make check-all                       # root gate + every sibling package's own gate
```

Individual steps: `./scripts/quality-gate.sh lint|typecheck|test|coverage`. Each sibling
package carries its own generated `scripts/quality-gate.sh` with its own coverage floor.

### End-to-end / user-journey harness

To exercise **everything** at once — every package suite, every `features.yaml` functionality
gate, every package CLI journey, the skill/hook e2e tests, and (credential-gated) live
integrations — run the one-command orchestrator and read the aggregated report from
`artifacts/e2e-report/`:

```powershell
pwsh scripts/run_all_e2e.ps1 -Tiers offline   # A–C, no network/credentials
pwsh scripts/run_all_e2e.ps1 -Tiers all       # + live tiers when creds are present
```

The sibling packages are made importable via `PYTHONPATH` (no install needed), and on this
Windows host a `scripts/e2e_shims/sitecustomize.py` neutralizes a hanging `platform` WMI call
that would otherwise wedge every pytest run. Skill tests that shell out to bash include a
`_bash_works()` probe that skips when the WSL shim cannot handle Windows-native temp paths,
and `test_symlinked_dir_is_not_a_member` skips on non-elevated Windows where symlink creation
raises `WinError 1314`. See [docs/e2e-runbook.md](docs/e2e-runbook.md)
for tiers, flags, credentials, and how to read the report.

Every package and skill enforces a **≥95% branch-coverage floor** (the root harness gate is
96%; the quality-gate tooling stays at 85% — its `git worktree`/subprocess paths are
impractical to cover further, see
[ADR 0009](docs/decisions/0009-tech-debt-audit-and-compat-surface.md)). Operational scripts
under `scripts/` carry their own **≥85% gate** (`scripts/.coveragerc`, F-031); the
`validations/F_*` gate scripts are excluded — they are one-shot CI checks executed via
`features.yaml`, not unit-test targets. Coverage is measured with `branch = true` across the
board. Each sub-package runs its own `ruff` + `mypy` + `pytest --cov` in CI across
Python 3.10–3.12. The measured 2026-07 baseline behind these numbers is recorded in
[docs/gap-analysis-2026-07.md](docs/gap-analysis-2026-07.md).

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
- **Skill-script drift guard** fails if a vendored skill copy of `scripts/validate_skill.py`
  diverges from the canonical repo-root copy (the copies are duplicated by design so each
  skill stays self-contained). Run `python scripts/check_skill_script_drift.py`. The
  rationale for the kept compatibility shims and the uniform 95% coverage floor is recorded
  in [`docs/decisions/0009-tech-debt-audit-and-compat-surface.md`](docs/decisions/0009-tech-debt-audit-and-compat-surface.md).
- **Public-surface backwards-compat guard** (`F-039`) freezes every package's public
  `__all__` exports — `tests/test_public_surface.py` + a committed
  `public_surface_baseline.json`, exact-equality checked — so a removed or renamed export
  fails CI instead of silently breaking every config/import that used it. Duplicated
  byte-identically (drift-guarded) into each of the 5 packages' own `tests/` dirs, since
  each runs its own isolated suite. `scripts/validations/F_039.py` guards the wiring.
- **Structural size budget** (ADR 0019) enforces two of the project's structural limits:
  cyclomatic complexity `< 15` repo-wide via ruff `C901` (`max-complexity = 14`), and source
  file length `≤ 500` lines via `python scripts/check_size_budget.py` (wired into
  `quality-gates.yml`). Function length (`≤ 50`) and public-method count (`≤ 15`) print as
  non-blocking warnings — run the gate locally to see the backlog.
- **Operational-scripts quality gates** (`F-031`) keep `scripts/` lint-clean (`ruff check` +
  `ruff format --check`), type-clean (`mypy scripts`), and coverage-gated at ≥85%
  (`scripts/.coveragerc`) in `eval-harness-ci.yml`; `scripts/validations/F_031.py` asserts the
  enforcement itself cannot silently regress. Baseline and rationale:
  [docs/gap-analysis-2026-07.md](docs/gap-analysis-2026-07.md).
- **Calibrated merge gate** (`F-010` / `F-032…F-035`, ADR 0005 + ADR 0018) is a pure
  `agent_core` decision subsystem that **auto-merges nothing** unless
  `ENABLE_CALIBRATED_AUTOMERGE` is set and a populated, human-audited outcome store has earned
  it. Real outcomes persist on the dedicated `merge-gate-data` branch; a daily labeller applies
  passive labels behind an anti-optimism guard, a weekly queue drives human `HUMAN_AUDIT`
  verdicts, and an always-on **shadow** job logs a decision on every PR without blocking one.
  **Agent-confidence seeding** (`F-042`, ADR 0023) routes each merged change by its PR head-ref
  prefix (`config/agent-authors.yaml`): agent changes are seeded in the agent domain with a
  deterministic proxy confidence (`scripts/agent_confidence.py` — diff shape only, no network),
  while human or unclassifiable changes stay in the reserved `human/<domain>` namespace at 0.0
  (fail-safe). The **calibration report** (`F-043`, `agent_core.calibration_report`) surfaces
  agent-domain ECE / Brier / AUROC / abstention (Wilson CIs, honest `DEGENERATE` guard) to the
  daily run summary. `scripts/validations/F_046.py` pins the hardening invariants.
- **Live Phoenix validation (opt-in)** — `.github/workflows/phoenix-live.yml`
  (`workflow_dispatch`, `timeout-minutes: 20`) validates the reversible Phoenix spike
  end-to-end on a networked runner: a `dep-resolve` dry-run job surfaces the
  `pyarrow>=14,<20` vs `arize-phoenix-evals` (`pandas`/`numpy`) constraint without
  installing, and a `live` job boots pinned `arize-phoenix==17.18.0` via `phoenix serve`
  and runs `tests/test_phoenix_live.py` against the real OTLP collector plus the Phoenix
  evals judge. See [`docs/phoenix-spike.md`](docs/phoenix-spike.md) for the reversible-
  adoption pattern.

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
  config/            versioned models, migrations, env-interpolating loader
  core/              types, interfaces, generic registry
  scorers/           exact_match, regex_match, contains, json_keys, llm_judge, weighted,
                     autoevals (bridges BrainTrust's autoevals scorer library)
  datasets/          inline, jsonl, langfuse, braintrust, csv, parquet
  targets/           echo, callable (dynamic import), model (alias llm; calls an
                     OpenAI-compatible / LM Studio / Nemotron endpoint)
  sinks/             console, json_file, html_file, langfuse, phoenix, braintrust
  judges/            mock (deterministic), openai (Nemotron/GPT), anthropic, bedrock,
                     phoenix_evals
  langfuse_client/   Langfuse tracing + score export (SDK-optional seam)
  phoenix_client/    Phoenix tracing + score export (SDK-optional seam; mirrors
                     langfuse_client — see docs/phoenix-spike.md)
  braintrust_client/ BrainTrust experiment export (SDK-optional seam; mirrors
                     phoenix_client — see docs/braintrust-spike.md)
  agent_core_adapter/  agent_core bridge (BudgetLedger, calibration surface, and the
                       BudgetedJudge cost-cap wrapper applied around another judge)
  gating/            config-driven quality gate
  engine.py          orchestration
  cli.py             entry point

scripts/
  .coveragerc             operational-scripts coverage gate (>=85%, F-031)
  _cli.py                 shared CLI helpers (configure_logging)
  init.py                 cross-platform project init (venv + editable install)
  validate.py             spec-driven project validation
  validate_skill.py       skill structural + behavioral validation (canonical copy)
  select_next.py          feature priority selector
  skill_marketplace.py    skill registry CLI (validate/verify/list)
  regression_gate.py      net-new lint/test diff vs an isolated HEAD baseline
  eval_protected_paths.py single source of truth for protected eval-defining paths
  check_protected_changes.py   CI guard: flags protected changes lacking approval
  check_skill_script_drift.py  CI guard: vendored skill scripts == canonical copy
  _config.py              shared changed-file + strict-YAML-loader helpers (merge-gate seeding)
  merge_gate_context.py   composes the merge-gate ChangeContext / seed (--confidence seam, F-042)
  agent_confidence.py     deterministic agent-lane proxy confidence for seeding (F-042, no network)
  migrations/             one-off reversible data migrations (agent_domain_backfill.py, F-044)
  fix_loop.py             auto-fix loop scaffolding (DESIGN-ONLY, disabled)
  run_all_e2e.ps1         one-command e2e/user-journey harness (all tiers -> artifacts/e2e-report/)
  e2e_shims/              sitecustomize.py: neutralizes the Windows platform-WMI hang for pytest
  validations/            per-feature validation scripts (F_0NN.py)

skills/
  marketplace.yaml          registry of local skills (schema in marketplace.schema.json)
  openai-judge/             OpenAI-compatible LLM judge evaluation
  architecture-drift-guard/ import-graph → C4 drift detector + mermaid freshness gate
  eval-corpus-forge/        synthetic-corpus construction and validation
  model-bench/              model benchmark orchestration
  project-setup/            deterministic Makefile generator (from detected toolchain)
  quality-gate/             deterministic lint+type+test+coverage gate-script generator
  deploy/                   safety-railed deployment-script generator (dry-run/confirm/rollback)

experiments/
  backend-validation/ isolated, temporary experiment (eval-backend-validation_v1): validates
                      Langfuse/Opik eval-backend capability claims against running deployments.
                      Own gate (`make -C experiments/backend-validation check`); consumes the
                      harness as a dependency only; ships unsigned (probes gated behind human
                      sign-off). Not a package/skill; not in `make check-all`.

docs/
  c4_architecture.md  hand-maintained C4 diagrams (runtime/call semantics; the import-edge view is generated at the repo root)
  e2e-runbook.md      how to run and read the one-command e2e harness
  decisions/          Architecture Decision Records (ADRs)
  gap-analysis-2026-07.md  measured lint/type/coverage baseline + remediation record
  plans/              cross-repo planning docs (claude-foundation plugin plan + review)
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

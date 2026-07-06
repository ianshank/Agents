# AGENTS.md

Orientation for coding agents working in this repository. Read this before making changes.

## What this is

`langfuse-eval-harness` — a dynamic, backwards-compatible enterprise LLM evaluation harness with
first-class Langfuse integration, a pluggable skill framework, and a calibrated merge-gate
subsystem. It is a **monorepo** of pure-Python packages plus vendored skills and CI tooling:

| Path | Package / role |
|------|----------------|
| `src/eval_harness/` | core harness — config, engine, scorers, judges, datasets, targets, sinks, gating, CLI (`eval-harness`) |
| `agent-core/` | deterministic control, calibration & merge-gate logic (`agent_core`); zero runtime deps |
| `behavioral-regression/` | behavioral drift detector (`bregress` / `python -m behavioral_regression`) |
| `flow-protocol/`, `flow-corpus/` | shared wire contract + calibrated flow corpus (airgap seam) |
| `claude-foundation/` | staging for a reusable Claude Code plugin (`foundation_tools` under `tools/`) |
| `skills/` | vendored evaluation skills (registered in `skills/marketplace.yaml`) |
| `scripts/` | operational tooling: `validate.py`, `validate_skill.py`, quality/regression gates, the e2e harness |

Architecture: [docs/c4_architecture.md](docs/c4_architecture.md) (canonical import graph in
`architecture.yaml`, rendered `architecture.mmd`). Feature registry: `features.yaml` (each feature
has a `validation_command`). Roadmap: [NEXT_STEPS.md](NEXT_STEPS.md). ADRs: `docs/decisions/`.

## Golden rules

- **No hard-coded values.** Behaviour comes from a validated config; defaults live on the schema;
  credentials come from environment variables only (see `.env.example`).
- **Backwards compatible.** Configs carry `schema_version` with a migration chain; registry aliases
  keep renamed component names resolving; contracts are ABCs.
- **Optional deps are lazy and reversible.** SDKs (Langfuse, Phoenix, OpenAI, Anthropic, Bedrock)
  import at instantiation, never at module load, and have offline/null fallbacks. Cover the
  SDK-absent path with `sys.modules` injection (`monkeypatch.setitem(sys.modules, "phoenix.otel", None)`),
  not by assuming the extra is uninstalled — this venv installs all extras.
- **Every package/skill enforces a branch-coverage floor** (root 96%, siblings 95%, foundation 85%,
  `scripts/` 85%). Don't lower a floor to go green.

## Eval-integrity guards — respect the protected surface

Because this is an evaluation harness, the cheapest way to make a check "pass" is to weaken the
evaluation. Two CI gates make that hard, and agents must not route around them:

- **Protected paths** (`scripts/eval_protected_paths.py`, `check_protected_changes.py`): changes
  under `features.yaml`, `config/`, `src/eval_harness/{gating,scorers,judges}/`, `scripts/validations/`,
  `tests/`, or `.github/` require a human-reviewed `eval-change-approved` label.
- **Skill-script drift** (`check_skill_script_drift.py`): `scripts/validate_skill.py` is duplicated
  byte-identically into each `skills/<skill>/scripts/`. If you edit the canonical copy, re-sync all
  vendored copies (`cp scripts/validate_skill.py skills/<skill>/scripts/`) or the guard fails.
- **Regression gate** (`regression_gate.py`, F-006): blocks net-new lint/test findings vs an isolated
  `HEAD` baseline.

## Running things

```bash
# Per-package (from the package dir, so its own config/coverage floor applies)
python -m pytest --cov --cov-report=term-missing
ruff check .          &&  ruff format --check .
mypy <package>
python scripts/validate.py            # runs every features.yaml validation_command
```

**Whole-repo pass — the e2e harness:** `pwsh scripts/run_all_e2e.ps1 -Tiers offline` runs every
suite, gate, CLI journey, and skill/hook e2e test and writes `artifacts/e2e-report/summary.md`.
See [docs/e2e-runbook.md](docs/e2e-runbook.md).

## Environment gotchas (this Windows host)

- **PyPI is TLS-blocked and the venv has no `setuptools`** — do not `pip install`. The sibling
  packages are not installed; make them importable via `PYTHONPATH` (order matters;
  `claude-foundation` exposes `foundation_tools` under `tools/`). The e2e harness does this for you.
- **`platform.uname()` hangs** here (WMI is blocked). Hypothesis calls it at import, so *every*
  pytest run wedges before collecting a test. Fix: put `scripts/e2e_shims/` on `PYTHONPATH` — its
  `sitecustomize.py` makes `platform._wmi_query` fail fast. The harness sets this automatically.
- **Cross-platform hygiene:** never let git-plumbing stdin go through text mode (CRLF translation
  corrupts `mktree`/`hash-object`); emit finding/path strings with `.as_posix()`; keep eval commands
  and generated YAML free of Windows `\` paths and POSIX-only shell (`/dev/null`, `test $?`, pipes) —
  use `sys.executable` + cross-platform python one-liners. These were real bugs; see the CHANGELOG.

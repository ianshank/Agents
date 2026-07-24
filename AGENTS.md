# AGENTS.md — orientation for coding agents

Instructions for autonomous coding agents (Claude Code, Codex, Copilot, Gemini)
working in this repo. Human-oriented docs live in [README.md](README.md) and the
per-package READMEs; this file is deliberately terser and points at authoritative
sources rather than restating them.

## What this repo is

A monorepo of five Python packages plus vendored skills and CI:

| Path | Role | Version gate |
|---|---|---|
| `src/eval_harness/` (root) | `langfuse-eval-harness` — LLM evaluation harness with pluggable judges, scorers, sinks, and datasets | `pyproject.toml [tool.coverage.report] fail_under = 96` |
| `agent-core/` | Deterministic control & calibration core; zero runtime deps | `agent-core/pyproject.toml fail_under = 95` |
| `behavioral-regression/` | Behavioral-regression detector + `ship/hold/escalate` gate | `behavioral-regression/pyproject.toml fail_under = 95` |
| `flow-corpus/` | Calibrated flow corpus (offline + deterministic) | `flow-corpus/pyproject.toml fail_under = 95` |
| `flow-protocol/` | Cross-package flow protocol | `flow-protocol/pyproject.toml fail_under = 95` |
| `scripts/` + `scripts/validations/` | Operational tooling — feature validators, CI guards | `scripts/.coveragerc fail_under = 85` |
| `skills/` | Vendored skills registered via `skills/marketplace.yaml` — eval skills plus deterministic generator skills (`project-setup`/`quality-gate`/`deploy`) that emit Makefiles/shell scripts (ADR 0020) | `skills/*` gate: pinned `ruff`/`mypy` + `pytest --cov-fail-under=95` per `skills-ci.yml` |

## The map

Before writing code, read in order:

0. `docs/CHARTER.md` — the north-star charter: Vision / Mission / Scope (+ non-goals) / Invariants / Roadmap. Changes rarely; keep work within its §3 scope and §4 invariants and escalate anything that would violate them. Drift-checked by `scripts/check_charter_drift.py`.
1. `README.md` — install / test / gate commands and repo layout.
2. `architecture.mmd` + `architecture.yaml` — the canonical **import-edge component view** (package-level import dependencies, drift-gated in CI). Agents MUST update it when adding or removing a component or import edge — by editing `architecture.yaml` and regenerating (`python skills/architecture-drift-guard/scripts/mermaid_gen.py --manifest architecture.yaml -o architecture.mmd`), never by hand-editing the `.mmd`. Runtime/call-semantics diagrams (C4 context, containers, sub-component internals) live in `docs/c4_architecture.md`.
3. `docs/decisions/` — Architecture Decision Records. **`ADR-0009`** is the tech-debt baseline: no hard-coded secrets, config-driven defaults, per-package coverage gates. **New code should not regress that baseline.**
4. `CHANGELOG.md` `[1.3.0-dev]` — the section to add entries to for any user-visible change. Follow the existing `Hardening` / `Added` / `Changed` / `Fixed` structure.
5. `docs/phoenix-spike.md` — reversible-adoption pattern the Phoenix seam demonstrates. Reference model for any future "SDK-optional" integration.

## Root documentation map

These root-level docs answer different questions; check this table before guessing which one
to read or update. Governance and community-health files (bottom rows) were added in the
enterprise-docs pass and point at the charter as the single source of truth:

| File | Answers | Currency |
|---|---|---|
| `README.md` | How do I install / run / test this? | Kept current with each release |
| `AGENTS.md` (this file) | What must an agent read or avoid before editing? | Manually maintained — see "Rebuilding this file" below |
| `HARNESS_SPEC.md` | What is the canonical spec (features, gates, checkpoints)? | Canonical source of truth (see its own header) |
| `NEXT_STEPS.md` | What shipped recently, what's next? | A rolling log of intent — an entry's `[x]` reflects the state *when written*, not necessarily now. Cross-check `features.yaml` / `scripts/validations/F_*.py` (run `python scripts/validate.py --tier fast`) for a feature's current enforced state rather than trusting the checkbox alone |
| `CHANGELOG.md` | What changed, release by release? | Keep-a-changelog format; append to the `[Unreleased]`/dev section |
| `progress.md` | What happened in each work session? | Rotates to `progress-archive/YYYY-MM.md` once large (see `HARNESS_SPEC.md`'s "progress-archive/" section) |
| `docs/README.md` | Where is every doc, by category? | The documentation index (mirrors this table) |
| `CONTRIBUTING.md` | How do I set up, test, and submit a change? | Generalizes `agent-core/CONTRIBUTING.md` to the monorepo |
| `GOVERNANCE.md` | Who decides, and how? | Defers to `docs/CHARTER.md` §3/§6 |
| `SECURITY.md` | How do I report a vulnerability? | Private GitHub advisories; reuses the Snyk/secret-scan posture |
| `SUPPORT.md` | Where do I ask for help? | Points at docs + issue templates |
| `CODE_OF_CONDUCT.md` | What behavior is expected? | Contributor Covenant 2.1 |
| `MAINTAINERS.md` | Who maintains this? | Derived from `.github/CODEOWNERS` |
| `LICENSE` / `NOTICE` | Under what terms is this licensed? | Apache-2.0 |

`docs/decisions/` ADR numbers are **not** contiguous by design — `0007` is an intentional
gap in the sequence (see `docs/plans/agents-critical-path/REVIEW.md`); do not backfill it
or renumber later ADRs to close it.

## What is off-limits without a labeled approval

The repo enforces protected paths via `scripts/check_protected_changes.py` and the `eval-change-approved` GitHub label. Do NOT modify these paths without asking:

- `features.yaml`
- `scripts/validations/*.py`
- `.github/**`
- `tests/**` — any new `tests/test_*.py` triggers the guard

Read `scripts/eval_protected_paths.py` for the authoritative list.

`scripts/validate_skill.py` is separately guarded by `check_skill_script_drift.py`: it is
duplicated byte-identically into each `skills/<skill>/scripts/`. If you edit the canonical
copy, re-sync every vendored copy (`cp scripts/validate_skill.py skills/<skill>/scripts/`) or
the drift guard fails.

## Non-negotiable constraints

Every one of these is enforced by CI. Failing any breaks the merge.

- **No hard-coded secrets, absolute paths, or production URLs in source.** Credentials come from environment variables (`LANGFUSE_*`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PHOENIX_COLLECTOR_ENDPOINT`, `AWS_*`). See `.env.example` for the canonical set.
- **No hard-coded numeric defaults at call sites.** They belong in a `*Config` dataclass field with the default documented on the field. Example: `JudgeBudgetConfig.skip_score` replaces a literal `0.0` at the call site.
- **`SCHEMA_VERSION` is single-sourced** in `src/eval_harness/version.py`. Do not touch it in a feature branch. Bumps happen in dedicated release commits and require migration code (see `src/eval_harness/config/migrations.py`).
- **`from_dict` is strict.** Unknown keys raise `ConfigError`. Do not add permissive fallbacks.
- **`ClaimId` is opaque `str`.** Never sanitize `CycleState.unresolved`.
- **Ruff and mypy are pinned** in the `dev` extra (`ruff==0.15.20`, `mypy==2.1.0`). Do not bump them casually — CI/local skew broke `ruff format --check` before.
- **Backwards-compat shims are documented.** `ece`/`expected_calibration_error` alias in `agent-core/agent_core/__init__.py` is deliberate. Do not remove without a separate deprecation ADR.

## Entry points

| Task | Command (repo root, from an activated venv) |
|---|---|
| Install harness with every optional integration | `pip install -e ".[dev,langfuse,openai,anthropic,bedrock,phoenix,phoenix-evals,braintrust,autoevals,parquet,archguard]"` |
| Install a sibling package | `pip install -e ./agent-core[dev]` (same for `behavioral-regression`, `flow-corpus`, `flow-protocol`) |
| Run the CLI | `eval-harness run --config config/eval.example.yaml` |
| Full offline gate (single source of truth; CI mirrors it) | `./scripts/quality-gate.sh all` — generated by the quality-gate skill; lint (ruff check + format), 3 per-path mypy runs, coverage ≥96, and the F-031 scripts gate (hand extension below the marker). `make check` delegates to it. |
| Whole-workspace gate (root + all 5 sibling packages) | `make check-all` — root gate plus `$(MAKE) -C <member> check` per member, each delegating to its own generated `scripts/quality-gate.sh` |
| **Whole-repo e2e / user-journey harness** | `pwsh scripts/run_all_e2e.ps1 -Tiers offline` — runs every package suite, `features.yaml` gate, package CLI journey, and skill/hook e2e test; report at `artifacts/e2e-report/`. See [docs/e2e-runbook.md](docs/e2e-runbook.md). |
| Live Phoenix e2e (mirrors `phoenix-live.yml`) | `docker run -p 6006:6006 arizephoenix/phoenix:17.18.0` then `pytest tests/test_phoenix_live.py -v -rs` with `PHOENIX_COLLECTOR_ENDPOINT` and `OPENAI_API_KEY` set |
| Regression sibling package | `pytest behavioral-regression/tests --cov=behavioral_regression` |
| Behavioural-regression detector CLI | `python -m behavioral_regression --config <cfg>` — see `behavioral-regression/README.md` |
| Eval-backend validation experiment | `make -C experiments/backend-validation check` (own gate) — an **isolated, temporary** subtree (`eval-backend-validation_v1`; Langfuse/Opik capability validation). Consumes the harness as a dependency only; zero writes outside itself; ships unsigned (probes gated behind human sign-off of `PROBES.yaml`/`RUBRIC.md`). NOT a package/skill and NOT in `make check-all`; see `experiments/backend-validation/README.md`. |

## Seams that must stay narrow

The following files implement "SDK-optional" seams: the real dependency is imported lazily so the package installs and the offline suite runs with **zero external dependencies**. Follow the same pattern for any new integration:

- `src/eval_harness/langfuse_client/__init__.py` — Langfuse tracing + score export.
- `src/eval_harness/phoenix_client/__init__.py` — Phoenix tracing + score export (mirrors `langfuse_client` deliberately; ROI matrix in `docs/phoenix-spike.md`).
- `src/eval_harness/braintrust_client/__init__.py` — BrainTrust experiment export (`build_client`) + dataset read (`fetch_dataset_items`); mirrors `phoenix_client`, `docs/braintrust-spike.md`.
- `src/eval_harness/judges/*.py` — `MockJudge` (offline default), `OpenAIJudge`, `AnthropicJudge`, `BedrockJudge`, `PhoenixEvalJudge`.
- `src/eval_harness/sinks/__init__.py` — `console`, `json_file`, `html_file`, `langfuse`, `phoenix`, `braintrust`.
- `src/eval_harness/scorers/__init__.py` — `autoevals` bridges BrainTrust's `autoevals` scorer library (heuristic offline-safe; LLM/Embedding need a provider key). `src/eval_harness/datasets/__init__.py` — `braintrust` pulls a dataset via `init_dataset` (fail-fast when the SDK is absent).

Test the "SDK absent" path via `sys.modules` injection, not `@patch(...)` — see `feedback_agents_offline_optional_dep_testing` behaviour documented in existing tests. `@patch("phoenix.otel.register")` raises `ModuleNotFoundError` at patch time when the SDK isn't installed. The concrete idiom is `monkeypatch.setitem(sys.modules, "phoenix.otel", None)`, which forces the lazy import to `ImportError` even when the extra *is* installed (this venv installs all extras).

## Testing conventions

- Every scorer, judge, sink, and dataset registers itself via `@REGISTRY.register("name")`. Tests should exercise the registered name path, not the class constructor path — that's how the real engine resolves them.
- Pytest markers: `integration` (live API tests, skipped by default), `slow` (>5s). Filter with `-m "not integration"` for the offline suite; only `test_phoenix_live.py` currently carries the `integration` marker for live-collector tests.
- Hypothesis: run with `HYPOTHESIS_PROFILE=ci` when reproducing CI behaviour locally (matches `agent-core-ci.yml`).
- Do NOT patch `os.environ.clear()` — replace with `monkeypatch.delenv` for surgical env manipulation. See `CHANGELOG.md` note under [1.2.0-dev] `Testing`.
- New tests trigger the protected-paths guard; adding a test file requires the `eval-change-approved` label on the PR.

## Windows / cross-platform gotchas

The offline suite must pass on Windows as well as Linux CI. Known traps (all were real bugs — see the CHANGELOG "Windows / cross-platform portability" entry):

- **`platform.uname()` hangs on some locked-down Windows hosts** (WMI blocked), and Hypothesis calls it at import — so *every* pytest run wedges before collecting a test. `scripts/e2e_shims/sitecustomize.py` neutralizes the hanging `platform._wmi_query`; put `scripts/e2e_shims/` on `PYTHONPATH` when running pytest by hand there (the e2e harness does this automatically).
- **Never send git-plumbing stdin through text mode.** `subprocess.run(..., text=True)` CRLF-translates `\n`→`\r\n` on Windows, which corrupts `mktree`/`hash-object` input (a tree entry name became `<file>\r`). Use byte I/O — see `agent_core.store_sync._run`.
- **Emit path/finding strings with `.as_posix()`**, not OS-native separators, so output is deterministic across platforms.
- **Keep eval commands and generated YAML free of Windows `\` paths and POSIX-only shell** (`/dev/null`, `test $? -eq 1`, pipes). `validate_skill.py` rewrites a standalone `python` token to `sys.executable`; write `command_exit_zero` evals as cross-platform python one-liners.
- **WSL bash cannot execute scripts at Windows paths.** `shutil.which("bash")`
  finds `C:\WINDOWS\system32\bash.EXE` (the WSL shim), which accepts `bash -c
  'echo ok'` but returns exit 127 when handed a Windows-native temp path.
  Skill tests that shell out to bash use a `_bash_works()` probe (creates a
  real temp `.sh` file and verifies execution) rather than a simple `BASH is
  not None` check.
- **Symlinks require elevation on Windows.** `Path.symlink_to()` raises
  `OSError` / `WinError 1314` unless the user has `SeCreateSymbolicLinkPrivilege`.
  Tests guarded by `_can_symlink()`.

## Logging

Standard library `logging` module. Modules obtain a logger via `logger = logging.getLogger(__name__)`. Do not call `logging.basicConfig` inside library code — it belongs in `scripts/_cli.configure_logging()` or a CLI entry point. When you add debug output to a new integration, prefer `logger.debug` for verbose per-call detail and `logger.info` for once-per-run summaries; test with `pytest -o log_cli=true --log-cli-level=DEBUG`.

## Where to put a design decision

- **Single-file change with clear reason:** commit message and a bullet in `CHANGELOG.md`.
- **Architectural choice affecting multiple files or a future contract:** new ADR at `docs/decisions/NNNN-<slug>.md`.
- **Cross-cutting analysis (baselines, gap analysis):** `docs/gap-analysis-<date>.md`.
- **Reversible integration spike:** `docs/<name>-spike.md` — see `docs/phoenix-spike.md` for the model.

## Pre-PR checklist

Before opening a PR, run all of:

```bash
make check-all                                     # root + every sibling package gate
                                                   # (each delegates to its generated
                                                   #  scripts/quality-gate.sh — lint, mypy,
                                                   #  pytest --cov with the package's floor)
pip install '.[phoenix-evals,parquet]' --dry-run                  # numpy/pyarrow resolve
```

On Windows, `pwsh scripts/run_all_e2e.ps1 -Tiers offline` is the equivalent whole-repo pass
(it applies the WMI shim and per-package coverage floors). If any step fails, do NOT push —
either fix the root cause or ask a human. Do not disable failing gates.

## Rebuilding this file

`AGENTS.md` is durable orientation, not a scratch pad. Update it when a component moves, a gate changes, a seam is added, or the constraints list evolves. Do NOT append transient notes or per-PR context — those belong in `CHANGELOG.md`.

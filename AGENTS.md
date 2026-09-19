# AGENTS.md — orientation for coding agents

Instructions for autonomous coding agents (Claude Code, Codex, Copilot, Gemini)
working in this repo. Human-oriented docs live in [README.md](README.md) and the
per-package READMEs; this file is deliberately terser and points at authoritative
sources rather than restating them.

## What this repo is

A monorepo of five Python packages plus vendored skills and CI. **Every component carries
its own `AGENTS.md`** with its gate command, coverage floor, seams and constraints — go
there, not here, once you know which one you are working in.

`src/eval_harness/` is the harness and the top of the dependency DAG. `agent-core/` and
`flow-protocol/` are pure leaves (`agent_core` has zero runtime dependencies).
`flow-corpus/` builds on both; `behavioral-regression/` is a terminal consumer.
`scripts/` holds the CI guards and `skills/` the vendored skills.

**The airgap:** `eval_harness` and `flow_corpus` must never import each other, and
`eval_harness` reaches `agent_core` only through `src/eval_harness/agent_core_adapter/`.
The absence of those edges in `architecture.yaml` *is* the structure; `drift_check.py` enforces it.

## The map

Before writing code, read in order:

0. `docs/CHARTER.md` — the north-star charter: Vision / Mission / Scope (+ non-goals) / Invariants / Roadmap. Changes rarely; keep work within its §3 scope and §4 invariants and escalate anything that would violate them. Its markdown links are drift-checked by `scripts/check_charter_drift.py`; its actual claims (package roles, invariants, default-off flags, ...) are mechanically re-checked by `scripts/check_charter_invariants.py`. See `docs/CHARTER_ALIGNMENT_AUDIT.md` for the audit that motivated the latter.
1. `README.md` — install / test / gate commands and repo layout.
2. `docs/quickstart.md` — 5-minute onboarding guide (install → config → run → Langfuse).
3. `architecture.mmd` + `architecture.yaml` — the canonical **import-edge component view** (package-level import dependencies, drift-gated in CI). Agents MUST update it when adding or removing a component or import edge — by editing `architecture.yaml` and regenerating (`python skills/architecture-drift-guard/scripts/mermaid_gen.py --manifest architecture.yaml -o architecture.mmd`), never by hand-editing the `.mmd`. Runtime/call-semantics diagrams (C4 context, containers, sub-component internals) live in `docs/c4_architecture.md`.
4. `docs/decisions/` — Architecture Decision Records. **`ADR-0009`** is the tech-debt baseline: no hard-coded secrets, config-driven defaults, per-package coverage gates. **New code should not regress that baseline.**
5. `CHANGELOG.md` `[1.3.0-dev]` — the section to add entries to for any user-visible change. Follow the existing `Hardening` / `Added` / `Changed` / `Fixed` structure.
6. `docs/roadmap/` — domain-specific engineering epics (Epic 1–5).
7. `docs/phoenix-spike.md` — reversible-adoption pattern the Phoenix seam demonstrates. Reference model for any future "SDK-optional" integration.

## Reasoning & Planning Skills

`skills/` holds composable reasoning skills that compose into an end-to-end research
pipeline ending in an OpenSpec package. See [skills/AGENTS.md](skills/AGENTS.md) for the
roster, the marketplace registration rules, and how to chain them.

## Root documentation map

The docs an agent writes *to* are listed below. For everything else — the full index by
category, including the community-health and governance files — see
[docs/README.md](docs/README.md), which is the canonical index this table used to duplicate.

| File | Write to it when |
|---|---|
| `CHANGELOG.md` | Any user-visible change. Append to `[1.3.0-dev]`, keep-a-changelog headings |
| `docs/decisions/NNNN-*.md` | The change is an architectural decision with lasting consequences |
| `docs/plans/<topic>/PLAN.md` | The change is a plan of work. It must also be listed in `docs/README.md` |
| `progress.md` | A session log entry. Rotates to `progress-archive/YYYY-MM.md` once large |
| `HARNESS_SPEC.md` | The canonical spec — features, gates, checkpoints — actually changed |
| `AGENTS.md` (this file) | A component moved, a gate changed, or a constraint was added or lifted |

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
- **An eval config is untrusted input, not data.** The `callable` target turns `params.path` into an import and a call, so it is gated by `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST` (unset means deny; matching is on module boundaries, never a string prefix — see ADR 0039). Dataset reads and sink writes are separately confined by `DATA_ROOT`/`OUTPUT_ROOT` (`src/eval_harness/core/_paths.py`; unset means unconfined, with one warning). Do not add a new config-driven filesystem or import path without routing it through one of these two gates.
- **`SCHEMA_VERSION` is single-sourced** in `src/eval_harness/version.py`. Do not touch it in a feature branch. Bumps happen in dedicated release commits and require migration code (see `src/eval_harness/config/migrations.py`).
- **`from_dict` is strict.** Unknown keys raise `ConfigError`. Do not add permissive fallbacks.
- **`ClaimId` is opaque `str`.** Never sanitize `CycleState.unresolved`.
- **Ruff and mypy are pinned** in the `dev` extra (`ruff==0.15.20`, `mypy==2.1.0`), single-sourced in `scripts/tool_versions.py` and lockstep-checked by `scripts/validations/F_055.py`. Do not bump them casually — CI/local skew broke `ruff format --check` before.
- **Invoke mypy as `python3 -m mypy`, never a bare `mypy` on `PATH`.** A stray non-project mypy install (e.g. from `uv tool install`) can shadow the project's pinned one and run with none of this repo's dependencies on its own path, producing spurious `import-untyped`/missing-stub errors (`yaml`, etc.) that look like real code defects but vanish under the correct interpreter. `quality-gate.sh`/every `Makefile` already do this correctly; this is only a trap for a manually-typed shell command.
- **Never word-split an externally-supplied value into a command.** Routing a workflow input through `env` stops *template* injection, but an unquoted `$VAR` in the `run:` block still splits on whitespace — and an appended duplicate flag wins, because argparse is last-wins. Build optional flags as a bash **array** and expand `"${ARR[@]}"`; an empty array vanishes, which is the only reason the unquoted form was ever tempting. This was a real vulnerability in `merge-gate-verdict.yml` (see the CHANGELOG "Security" entry); `F_047.py` now fails if the array expansion is replaced.
- **A probability is validated through `agent_core.audit_sampler.is_valid_propensity` and rendered through `format_propensity`, never a restated comparison or a local format spec.** `float()` parses `"nan"` and `"inf"` happily, so parsing is not validation, and the naive `0.0 < p <= 1.0` form is correct only by the accident of NaN comparing false. **Rendering is serialisation, not decoration:** the output is pasted into a `gh workflow run` command, so it must parse back to the *same usable value* — fixed-point `.6f` collapsed `1e-7` to `"0.000000"`, which the contract then rejects. Use significant figures and property-test the round trip over the whole domain; hand-picked examples will miss it. Defining a shared helper is not the same as using it — `F_047` fails on a local `.6f` because two sites, including the `selected.txt` writer, had bypassed the helper.
- **Backwards-compat shims are documented.** `ece`/`expected_calibration_error` alias in `agent-core/agent_core/__init__.py` is deliberate. Do not remove without a separate deprecation ADR. The same applies to the re-exports left by the 500-line file split (ADR 0026): PPI moved to `agent_core/ppi.py` and the calibration report to `report_types.py` + `calibration_report_render.py`, but every previously importable name still resolves from its original module — `calibration_report.__all__` pins that promise and the public-surface guard freezes it.

## Entry points

| Task | Command (repo root, from an activated venv) |
|---|---|
| Install harness with every optional integration | `pip install -e ".[dev,langfuse,openai,anthropic,bedrock,phoenix,phoenix-evals,braintrust,autoevals,parquet,archguard]"` |
| Install a sibling package | `pip install -e ./agent-core[dev]` (same for `behavioral-regression`, `flow-corpus`, `flow-protocol`) |
| Run the CLI | `eval-harness run --config config/eval.example.yaml` |
| **Tier A mechanical gate runner** | `python scripts/verify_tier_a.py` or `make verify-tier-a` — 11 deterministic quality gates in <60s |
| Full offline gate (CI mirrors it) | `./scripts/quality-gate.sh all` — generated; lint, three per-path mypy runs, coverage >=96, and the F-031 scripts gate. `make check` delegates to it |
| Whole-workspace gate | `make check-all` — the root gate plus `make -C <member> check` for all five |
| **Whole-repo e2e / user-journey harness** | `bash scripts/run_all_e2e.sh --tiers offline` (POSIX; `pwsh scripts/run_all_e2e.ps1 -Tiers offline` on Windows). Both drivers declare the same steps and `tests/test_e2e_driver_parity.py` fails on drift. See [docs/e2e-runbook.md](docs/e2e-runbook.md) |

Per-eval invocations (RCA F-067, requirements F-068, testgen F-069, replay F-070) are in
[config/AGENTS.md](config/AGENTS.md) and [corpora/AGENTS.md](corpora/AGENTS.md); the two
isolated experiment gates are in [experiments/AGENTS.md](experiments/AGENTS.md).

## Seams that must stay narrow

Every integration imports its real dependency **lazily**, so the package installs and the
offline suite runs with zero external dependencies. Follow that pattern for any new
integration, and test the "SDK absent" path via `sys.modules` injection
(`monkeypatch.setitem(sys.modules, "phoenix.otel", None)`) rather than `@patch(...)`,
which raises `ModuleNotFoundError` at patch time when the SDK is genuinely absent.

The roster of seams, and why each one is shaped the way it is, lives in
[docs/seams.md](docs/seams.md) — read it before adding a seam or changing an existing one.

## Testing conventions

- Every scorer, judge, sink, and dataset registers itself via `@REGISTRY.register("name")`. Tests should exercise the registered name path, not the class constructor path — that's how the real engine resolves them.
- All evaluation components (Judges, Datasets, Scorers, Sinks) that interact with external dependencies must be fully mocked for offline testing using deterministic dependency injection as seen in `tests/test_matrix_eval_tools.py`. Do not use hardcoded `try...except` exception swallows or brittle magic mock returns.
- Registered components carry a **matrix obligation** (ADR 0032): rows in `tests/test_matrix_eval_tools.py` to the kind's `REQUIRED_DIMS` floor, declared with literal `MATRIX_KIND`/`MATRIX_COMPONENTS` class attributes and `test_m<dim>_*` method names — both cross-checked against the live-registry census by `tests/test_matrix_coverage.py`, so the declarations cannot go stale. Waivers are data with reasons (`WAIVED` in `tests/_matrix_coverage.py`), never silent omissions. After adding or renaming rows, regenerate the artifact with `python tests/test_matrix_coverage.py --update`; never hand-edit `docs/matrix-coverage.md`.
- Pytest markers: `integration` (live API; each test skips on its own env-var check, not a default `-m` deselect, so `tests/integration/` is still collected by the coverage gate), `slow` (>5s), `property` (Hypothesis). Run Hypothesis with `HYPOTHESIS_PROFILE=ci` to reproduce CI: profiles are `dev` (50 examples) and `ci` (500, no per-example deadline).
- Do NOT patch `os.environ.clear()` — replace with `monkeypatch.delenv` for surgical env manipulation. See `CHANGELOG.md` note under [1.2.0-dev] `Testing`.
- New tests trigger the protected-paths guard; adding a test file requires the `eval-change-approved` label on the PR.

## Windows / cross-platform gotchas

The offline suite must pass on Windows as well as Linux CI. Two traps bite often enough to
name here: **never send git-plumbing stdin through `text=True`** (CRLF translation corrupts
`mktree`/`hash-object` input), and **emit path strings with `.as_posix()`** so output is
deterministic across platforms.

The full list — the WMI/Hypothesis import hang, the WSL bash path trap, symlink elevation —
is in [docs/windows-gotchas.md](docs/windows-gotchas.md). Read it when a test passes on
Linux and fails on Windows, or before writing anything that shells out.

## Logging

Standard library `logging` module. Modules obtain a logger via `logger = logging.getLogger(__name__)`. Do not call `logging.basicConfig` inside library code — it belongs in `scripts/_cli.configure_logging()` or a CLI entry point. When you add debug output to a new integration, prefer `logger.debug` for verbose per-call detail and `logger.info` for once-per-run summaries; test with `pytest -o log_cli=true --log-cli-level=DEBUG`.

## Agents, skills, and hooks (`.claude/` and `.agents/`)

Subagents, skills and hooks are documented where they live: [.claude/README.md](.claude/README.md)
for the agent roster and the five hooks, and [.agents/AGENTS.md](.agents/AGENTS.md) for the
parallel tree that **Claude Code never reads**. Do not add a hook without reading the first.

## Pre-PR checklist

Before opening a PR, run all of:

```bash
python scripts/verify_tier_a.py                  # 11-gate mechanical gate in <60s (make verify-tier-a)
python scripts/generate_eval_metrics.py --check  # eval metrics freshness (make eval-metrics-check)
python scripts/check_agents_md.py                # per-directory AGENTS.md coverage and budget
make check-all                                   # root + every sibling package gate, each
                                                 # delegating to its generated quality-gate.sh
pip install '.[phoenix-evals,parquet]' --dry-run # numpy/pyarrow resolve
```

If the matrix freshness gate fails (`docs/matrix-coverage.md` stale), the remedy is
`python tests/test_matrix_coverage.py --update` — never a hand edit to the generated file
(`--update` refuses to write while the matrix itself has holes; fix the rows first).
`make check-all` is not the whole CI surface: `quality-gates.yml` also runs the merge-marker
sweep, `uv lock --check`, the skill-script drift guard, size budget, guard reachability, charter drift/invariants, the
validator battery (`python scripts/validate.py --tier fast --strict-git`) and the tooling
coverage step — run those too when touching `scripts/`, workflows, or `features.yaml`.

On Windows, `pwsh scripts/run_all_e2e.ps1 -Tiers offline` is the equivalent whole-repo pass.
If any step fails, do NOT push — fix the root cause or ask a human. Never disable a gate.

## Rebuilding this file

`AGENTS.md` is durable orientation, not a scratch pad. Update it when a component moves, a gate changes, a seam is added, or the constraints list evolves. Do NOT append transient notes or per-PR context — those belong in `CHANGELOG.md`.

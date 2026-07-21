# E2E / user-journey test runbook

`scripts/run_all_e2e.ps1` runs **every** test across the monorepo — package suites,
functionality gates, user-journey CLIs, and (credential-gated) live integrations — in one
command, and writes one aggregated report to `artifacts/e2e-report/`.

## Prerequisites

- The provisioned virtualenv at `.venv/` (Python 3.12). Every SDK is already installed;
  **do not** run `pip install` (PyPI is TLS-blocked here and `setuptools` is absent).
- Windows PowerShell 5.1 **or** PowerShell 7+ (the script is compatible with both).
- For live tiers only: real credentials in `.env` (see below) and, for Phoenix, a running
  collector.

The sibling packages (`flow_protocol`, `flow_corpus`, `behavioral_regression`,
`foundation_tools`, `agent_core`) are **not installed** — the runner makes them importable via
`PYTHONPATH` and verifies it with a pre-flight import guard that aborts the run if any import
fails. This prevents the failure mode where a bad path makes pytest silently collect 0 tests and
still report success.

**Windows WMI shim (critical).** On this host, Python 3.12's `platform.uname()` hangs forever in
`platform._wmi_query()` (WMI is blocked). Hypothesis calls `platform.system()` at import, and
Hypothesis is an auto-loaded pytest plugin — so without a workaround **every** pytest suite hangs
before collecting a single test. The runner prepends `scripts/e2e_shims/` to `PYTHONPATH`; it
contains a `sitecustomize.py` that makes `_wmi_query` fail fast so `platform` uses its
subprocess-free fallback. If you invoke pytest by hand here, add that dir to `PYTHONPATH` too, or
your run will hang.

## Usage

```powershell
# From the repo root (Agents-e2e/):
pwsh scripts/run_all_e2e.ps1 -Tiers offline          # Tiers A–C, no network, no creds
pwsh scripts/run_all_e2e.ps1 -Tiers all              # + Tier D live (skips steps missing creds)
pwsh scripts/run_all_e2e.ps1 -Tiers all -HypothesisProfile ci   # thorough property tests
pwsh scripts/run_all_e2e.ps1 -Tiers all -IncludeEnterprise      # + Tier E Enterprise live suite
pwsh scripts/run_all_e2e.ps1 -Tiers offline -FailFast           # stop at first failure
```

`windows powershell` users: substitute `powershell` for `pwsh`, or run
`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run_all_e2e.ps1 -Tiers offline`.

### Flags

| Flag | Values | Default | Meaning |
|------|--------|---------|---------|
| `-Tiers` | `offline` \| `live` \| `all` | `all` | `offline` = A–C; `live`/`all` = A–D |
| `-HypothesisProfile` | `dev` \| `ci` | `dev` | `ci` runs the thorough property-based tests |
| `-FailFast` | switch | off | Stop at the first FAIL |
| `-IncludeEnterprise` | switch | off | Also run the Enterprise live suite (Tier E) |

## What each tier does

- **Tier A — package suites (offline, always).** `pytest --cov` for the root harness,
  `agent-core`, `behavioral-regression`, `flow-corpus`, `flow-protocol`, `claude-foundation`, plus
  the operational-scripts coverage gate. Each runs from its own directory so its own coverage floor
  and markers apply, and each suite must collect **> 0** tests or it is failed.
- **Tier B — functionality gates (offline, always).** `scripts/validate.py -v` runs every
  `features.yaml` `validation_command` (the 36 `F_*` gates). Deferred features (e.g. **F-036**,
  which has no `F_036.py`) are skipped by design — that is expected, not a gap. **F-006/F-007** are
  the slow ones (they materialize a git worktree baseline).
- **Tier C — user-journey / CLI e2e (offline, always).** The three skill/hook `*e2e*`/
  `test_end_to_end.py` files, plus every package CLI: `eval-harness`
  (`list-plugins`/`run`/`compare`/`campaign`), `bregress` (`python -m behavioral_regression`),
  `python -m agent_core.merge_gate_ci`, and `scripts/skill_marketplace.py`. The `compare`/`campaign`
  fixtures are generated into `artifacts/e2e-report/fixtures/` at runtime (the `config/` dir is a
  protected path, so nothing is written there).
- **Tier D — live integrations (credential-gated).** Langfuse + Phoenix smokes, a live judge run
  per provider (OpenAI/Anthropic/Bedrock), and live Langfuse/Phoenix **sink** journeys. Each step
  **SKIPs** (not fails) when its credentials are absent; a step whose credentials *are* present but
  errors is a **FAIL**.
- **Tier E — Enterprise live suite (opt-in).** The `pytest.mark.integration` suite under
  `../Enterprise/files/langfuse-eval-harness/langfuse-eval-harness/tests/integration/`.

### Windows-specific caveats

- **WSL bash skip guards.** Skill tests that shell out to bash skip on Windows
  when `shutil.which("bash")` finds the WSL shim (which cannot handle
  Windows-native temp paths).  The `_bash_works()` probe creates a real temp
  script and verifies execution; tests skip if it fails.
- **Symlink privilege.** `test_symlinked_dir_is_not_a_member` skips on
  non-elevated Windows where `Path.symlink_to()` raises `WinError 1314`.
- **`--junitxml` string interpolation.** The `e2e:backend-validation` step's
  `--junitxml` flag must use PowerShell string interpolation
  (`"--junitxml=$var"`) not concatenation (`'--junitxml=' + $var`) — the
  latter silently splits into two array elements in `@()` context.

## Credentials that gate live steps (`.env`)

The runner loads `.env` from the repo root (BOM-safe). Each live step runs only when its vars are set:

| Live step | Required env vars |
|-----------|-------------------|
| `live:langfuse-smoke`, `live:langfuse-sink` | `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_BASE_URL` |
| `live:phoenix-smoke`, `live:phoenix-sink` | `PHOENIX_COLLECTOR_ENDPOINT` (+ a running collector) |
| `live:judge-openai` | `OPENAI_API_KEY` (model via `OPENAI_JUDGE_MODEL`, default `gpt-4o-mini`) |
| `live:judge-anthropic` | `ANTHROPIC_API_KEY` (model via `ANTHROPIC_JUDGE_MODEL`, default `claude-haiku-4-5-20251001`) |
| `live:judge-bedrock` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (model via `BEDROCK_JUDGE_MODEL`) |

Start a local Phoenix collector for the Phoenix steps:

```bash
docker run -p 6006:6006 arizephoenix/phoenix
# then set PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006 in .env
```

## Reading the report

`artifacts/e2e-report/` (recreated each run) contains:

- `summary.md` — a table of every step (Tier, Step, Status, Detail, ms) plus PASS/FAIL/SKIP totals.
- `summary.json` — the same data, machine-readable for CI.
- `<step>.log` — full stdout/stderr for each step.
- `*.xml` — one JUnit file per pytest suite.
- `fixtures/` — the generated offline `compare`/`campaign` (and live) config fixtures.

**Exit code:** non-zero if any step is **FAIL**. All-`SKIP` live steps keep the run green, so
`-Tiers all` with no credentials still exits 0 (Tiers A–C green, Tier D all SKIP).

## Test status on this checkout

A clean `-Tiers offline` run reports **21 PASS / 0 FAIL**. Nine cross-platform root causes were
found and fixed:

| Area | Root cause | Fix |
|------|-----------|-----|
| `agent-core` store_sync (4 tests) | `_run` used `text=True`; Windows CRLF-translated git plumbing stdin, so `mktree` wrote a filename ending in `\r` and `git show ...:merge_outcomes.jsonl` couldn't find it | `store_sync._run` now uses binary stdin/stdout (UTF-8), so `\n` stays `\n` |
| `claude-foundation` findings (1 test) | `validate.py` emitted OS-native `\` separators in findings | emit `.as_posix()` (portable forward slashes) |
| drift e2e (6 tests) | test wrote a Windows `\` path into a **YAML double-quoted** scalar → invalid escape sequences → unparseable manifest | build the manifest path with forward slashes |
| Phoenix (3 tests) | env-fragile: asserted the **SDK-absent** path but this venv installs all extras | made hermetic via `sys.modules[...] = None` injection (the repo's own idiom) |
| `claude-foundation` symlink (1 test) | `os.symlink` needs Windows Developer Mode (`WinError 1314`) | skip cleanly when symlink creation is denied |
| `features:validate.py` / F-009 (drift skill behavioral evals) | `validate_skill.py` ran eval commands with bare `python` (resolved via Windows PATH to a non-venv Python 3.11 without grimp), and 3 `command_exit_zero` evals used POSIX-only shell (`/dev/null`, `test $? -eq 1`, pipes) | `validate_skill._run_eval` rewrites a standalone `python` token to `sys.executable` and runs on the native shell; the 3 POSIX eval commands in `architecture-drift-guard/evals/evals.json` were rewritten as cross-platform python one-liners. Change mirrored across all 5 drift-guarded `validate_skill.py` copies |
| `e2e:backend-validation` (0 tests collected) | `--junitxml` flag used PS 5.1 string concatenation (`'--junitxml=' + $var`) in `@()` array literal, silently splitting into two elements — pytest received the XML path as a test directory | Use string interpolation (`"--junitxml=$var"`) matching all other suites; also save/restore PYTHONPATH around the step |
| `e2e:skills+hooks` (bash tests fail) | WSL bash (`C:\WINDOWS\system32\bash.EXE`) resolves on `shutil.which` but cannot handle Windows-native temp paths (exit 127); also `Path.symlink_to()` raises `WinError 1314` without elevation | `_bash_works()` probe creates a real temp script and verifies execution; `_can_symlink()` probe tests actual symlink creation; both skip cleanly |
| `features:validate.py` / F-038 | `ModuleNotFoundError` for `eval_harness.braintrust_client` when running standalone (stale editable install) | Prepend `src/` to `sys.path` in the validation script's bootstrap |

Notes on protected/shared surfaces touched by these fixes (relevant on a PR):
- The Phoenix fix edits three files under the **protected** root `tests/` path → needs the
  `eval-change-approved` label. Non-weakening: the failsafe path is now tested deterministically
  in any environment.
- The F-009 fix edits the **drift-guarded canonical** `scripts/validate_skill.py`; all four
  vendored skill copies were re-synced so `check_skill_script_drift.py` stays green.

## Troubleshooting

- **Pre-flight import guard fails** → a sibling package moved or the venv changed. Check
  `artifacts/e2e-report/preflight-imports.log`.
- **A suite reports `exit 0 but 0 tests collected`** → treated as FAIL on purpose; usually a
  `PYTHONPATH`/collection problem, not a real pass.
- **Tier B slow** → `F-006`/`F-007` build a git worktree and re-run the suite; expected.
- **Live step FAIL vs SKIP** → SKIP means creds absent; FAIL means creds present but the call
  errored (bad key, unreachable collector, quota). Check the step's `.log`.
```

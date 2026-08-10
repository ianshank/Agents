# E2E / user-journey test runbook

`scripts/run_all_e2e.ps1` runs **every** test across the monorepo — package suites,
functionality gates, user-journey CLIs, and (credential-gated) live integrations — in one
command, and writes one aggregated report to `artifacts/e2e-report/`.

## Prerequisites

- A virtualenv at `.venv/` (Python 3.12) with every SDK installed. **A fresh one can be
  built** — the previous "PyPI is TLS-blocked here" note was wrong, or has stopped being
  true. Verified 2026-08-08: `pip` reaches PyPI unaided, and a full from-scratch install of
  all extras plus the five sibling packages succeeds. Two caveats on a TLS-intercepting
  host:
  - **`uv` needs `--native-tls` on every invocation** (`uv venv --native-tls`,
    `uv pip install --native-tls …`). Without it: `invalid peer certificate: UnknownIssuer`.
    uv bundles its own roots and will not see a corporate CA; pip uses the OS store already.
  - **SDKs that verify via `certifi` (Langfuse's httpx client) fail with
    `CERTIFICATE_VERIFY_FAILED`.** `pip install truststore` and the affected code path can
    route verification through the OS trust store. This is *stricter* than the workarounds
    people reach for — it still verifies, just against the certificates the machine trusts.
- Windows PowerShell 5.1 **or** PowerShell 7+ (the script is compatible with both).
  **Launch from `powershell.exe`, not Git Bash** — `shutil.which("bash")` resolves
  differently between them, which silently changes whether the 12 `_bash_works()`-gated
  skill tests execute or skip.
- For live tiers only: real credentials in `.env` (see below) and, for Phoenix, a running
  collector. Set `LOCAL_MODEL_ID` to use a real model as the live target and judge (below).

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
  `features.yaml` `validation_command` (the `F_*` gates — one per done + fast feature). Deferred features (e.g. **F-036**,
  which has no `F_036.py`) are skipped by design — that is expected, not a gap. **F-006/F-007** are
  the slow ones (they materialize a git worktree baseline). A dedicated
  `matrix:coverage-check` step then runs `python tests/test_matrix_coverage.py --check`
  (F-053): the generated `docs/matrix-coverage.md` must match a live regeneration —
  registry census, per-kind dimension floors, and waiver/alias hygiene included.
- **Tier C — user-journey / CLI e2e (offline, always).** The seven skill/hook e2e /
  generator test files, plus every package CLI: `eval-harness`
  (`list-plugins`/`run`/`compare`/`campaign`), `bregress` (`python -m behavioral_regression`),
  `python -m agent_core.merge_gate_ci`, the read-only agent-core reporting CLIs
  (`merge_seed` -> `audit_sampler select --with-propensity` -> `record
  --selection-propensity` -> `calibration_report` under BOTH estimators -> `proxy_eval`
  with a JSON parse check), and `scripts/skill_marketplace.py`. The reporting steps must
  exit 0 — unlike the gate CLI, whose 0/10/20 are all valid decisions — because they are
  read-only and never influence a merge. The `compare`/`campaign`
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

## Test matrix artifact

`artifacts/e2e-report/` is gitignored and recreated per run, so it cannot be reviewed or
compared over time. `docs/e2e-matrix/` is the committed rendering of one run:

```bash
python tests/test_e2e_matrix.py --update      # regenerate from artifacts/e2e-report/
python tests/test_e2e_matrix.py --check       # exit 1 if the committed artifact is stale
```

It emits markdown, one CSV per sheet, and (with `pip install -e ".[e2e-matrix]"`) an
`.xlsx` workbook. The step list is parsed from this runner rather than restated, so adding
a step here puts it in the matrix automatically — and a step that appears in a run report
but not in the parse is a hard error. See
[ADR 0033](decisions/0033-generated-e2e-matrix-workbook.md) and
[docs/e2e-matrix/README.md](e2e-matrix/README.md).

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

A clean **`-Tiers all`** run reports **36 PASS / 0 FAIL / 2 SKIP** (38 steps: 1 pre-flight,
7 Tier A, 2 Tier B, 21 Tier C, 7 Tier D). The only two SKIPs are `live:judge-anthropic` and
`live:judge-bedrock`, which need cloud credentials; every other live step, including a real
model round-trip, passes. `-Tiers offline` reports 29 PASS / 0 FAIL of 31 steps.

**Assert the exact step list, not a count.** "step count ≥ 30" is satisfied by an offline
run, which never executes the tier most worth exercising — the same false-green shape as
D-2 below, reproduced in the success criteria.

Suite sizes with every extra installed: root 1504, agent-core 790, behavioral-regression
157, flow-corpus 163, flow-protocol 21, claude-foundation 136, skills+hooks 85,
backend-validation 211. These are substantially higher than earlier records (root was 995)
because a venv carrying every optional SDK stops `pytest.importorskip` from skipping —
roughly 700 additional tests actually execute. A *flat* count after installing more extras
means the install did not take.

Twelve cross-platform root causes have been found and fixed. The first nine came from an
earlier campaign; **W-01, W-02 and D-1/D-2/D-3 (2026-08-08) are new** and are listed after
the original table.

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

### 2026-08-08 campaign — fresh clone, all extras, live tier

| ID | Area | Root cause | Fix |
|----|------|-----------|-----|
| W-01 | charter invariants (1 test) | `check_quality_gates_wired` was changed to emit `path.as_posix()` on 2026-08-06 (`6c507d8`); the test asserting that output was last touched 2026-07-31 and still built its expectation with `str(tmp_path / …)`. Identical strings on Linux, backslashes on Windows | build the expectation with `.as_posix()` |
| W-02 | charter invariants (1 test) | `check_magic_number_defaults` interpolated `path.relative_to(root)` directly, emitting `flow-corpus\thing.py` — inconsistent with `.as_posix()` two functions away, and unmatched by any consumer keying on `/` | `.as_posix()` |
| D-1 | Tier D (2 steps) | The langfuse/phoenix smoke steps invoked `artifacts/*_smoke.py`. Those scripts do not exist at origin and `artifacts/` is gitignored, so they could not exist in any clone | scripts written into tracked `scripts/smokes/`, sharing `_smoke_lib.py` |
| D-2 | Tier D (2 steps) | D-1 reported **SKIP**, not FAIL: a missing file makes python exit 2, and 2 was the declared skip code, so "broken" and "no credentials" were indistinguishable | skip code is now **78/EX_CONFIG**, which neither a missing file nor an `argparse` error can forge; `Test-StepScript` added as a third anti-vacuous-pass guard |
| D-3 | Tier D (3 steps) | The "live" journeys were mocked — `judge: {type: mock}` returned a constant 0.9 and `target: {type: echo}` never called a model, so no live step performed a real round-trip | both driven by `LOCAL_MODEL_ID` against any OpenAI-compatible endpoint; falls back to echo+mock when unset |

**Where the smokes live, and why it matters.** `scripts/smokes/`, not a top-level `tools/`.
A `tools/` directory sits outside *three* gates simultaneously — `--cov=scripts` (the 85%
floor in `scripts/.coveragerc`), `mypy scripts` (`quality-gate.sh`), and
`check_charter_invariants._MISSION_DIRS` — so anything added there is unmeasured, untyped
and unscanned by default. The first draft of these scripts did live in `tools/`,
justified as "live-network code has no offline tests"; moving them under `scripts/`
immediately surfaced 12 mypy errors and 5 ruff violations that had been silently
swallowed. They now carry 58 tests at 96–100% coverage inside the existing gate, with no
new config: `scripts/smokes` is on `mypy_path` for the same reason `scripts/validations`
is (both are invoked as plain scripts and bootstrap a sibling import).

**Both smokes needed two iterations to become non-vacuous** — each naive version passed
against a dead backend, which is worth internalising before writing the next one:

- **Phoenix**: OTLP export is fire-and-forget. With nothing listening, `register()` succeeds,
  `force_flush()` reports no error, and the span is silently dropped. A TCP reachability
  probe against the endpoint is required; `configure_tracing() is not None` is not enough
  (it is contractually forbidden from raising, so it returns `None` on every failure).
- **Langfuse**: `log_score`/`flush` route transport errors to the SDK's own logger and
  return normally — the first version printed OK and exited 0 while the SDK emitted
  "Unexpected error occurred" on every call. `Langfuse.auth_check()` is the only call that
  actually reports failure.

### Live target and judge (`LOCAL_MODEL_ID`)

Set `LOCAL_MODEL_ID` to a model served by any OpenAI-compatible endpoint (LM Studio, Ollama,
vLLM) and the Tier-D journeys use a real `model` target and a real `openai` judge instead of
`echo`/`mock`. `OpenAIJudge` documents LM Studio support explicitly. Put the endpoint in the
environment, not the fixture:

```
OPENAI_API_KEY=lm-studio          # any non-empty value; local servers ignore it
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_JUDGE_MODEL=<model id>
LOCAL_MODEL_ID=<model id>
```

Setting `OPENAI_BASE_URL` **without** `OPENAI_JUDGE_MODEL` is a trap: the existing
`live:judge-openai` step defaults to `gpt-4o-mini`, so it would ask the local server for a
model it does not have. Set all four together, and the *existing* judge step becomes a real
local round-trip with no runner change. Keep `max_tokens` at the judge's 4096 default —
a reasoning model given a small budget returns its output in `reasoning_content` and leaves
`content` empty.

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

# Gap-Analysis Round — 2026-07 — `py.typed` mypy fallout

A follow-up to [`gap-analysis-2026-07-remediation.md`](gap-analysis-2026-07-remediation.md),
run on the `claude/charter-gcp-drone-comms-7u7k8s` branch. An objective scan (CI-matching
venv: `.[dev,langfuse,openai,parquet]` + the four sibling packages, mypy 2.1.0 / ruff 0.15.20)
found the monorepo's tests and coverage healthy, but surfaced a **CI-red regression and a set
of latent type errors that a prior change had masked** — all traced to one root cause.

## Root cause

PR #44 ("ship `py.typed` for the root `eval_harness` package (PEP 561)") made the package
advertise itself as typed. Two consequences had been invisible because the first aborted CI
before the rest could run:

1. **`mypy src/eval_harness` failed** with *"Source file found twice under different module
   names: `src.eval_harness.core.interfaces` and `eval_harness.core.interfaces`"*. With
   `py.typed` present, mypy now follows the editable-installed `eval_harness`, so the same
   file is reachable both via the CLI path (`src.eval_harness.*`) and the installed name
   (`eval_harness.*`). This was the exact error on `main`'s own CI at the branch base commit
   (`1fb53b9`) — a pre-existing red, not introduced here.
2. Because CI step `mypy src/eval_harness` aborted first, the later `mypy scripts` /
   `mypy tests` steps never ran — hiding **32 real type errors** that `py.typed` exposed once
   `eval_harness`'s true types (rather than `Any`) reached its callers.

## Fixed this round

| # | Finding (evidence) | Fix | Category |
|---|---|---|---|
| A | `mypy src/eval_harness` "source found twice" (repro'd; identical on `main@1fb53b9`) | Added `src` to `[tool.mypy].mypy_path` (with `explicit_package_bases`, already set) so the file resolves under one name, `eval_harness.*`. Config-only; no `__init__.py` shim or CI-flag workaround. The `mypy_path` change from a bare string to a list also required loosening `F_031`'s guard, which asserted the exact literal `mypy_path = "scripts/validations"`; it now asserts the actual invariant (`scripts/validations` is *an entry of* `mypy_path`), so a legitimate extra base no longer trips it while an accidental removal still does | correctness / CI unblock |
| B | 21 errors across `scripts/validations/F_018,F_024,F_025,F_026,F_027` — configs built as `EvalConfig(field={dict}, ...)`, now type-mismatched against the typed pydantic fields | Switched to `EvalConfig.model_validate({...})` / `ABCampaignConfig.model_validate({...})` — the repo's own idiom (already used in `tests/test_campaign.py`, `test_comparison.py`, `test_phoenix_cli.py`). Behaviour-identical (pydantic validates dicts either way) and now exercises the real strict-validation path | reusable idiom / no hard-coded change |
| C | `F_025` `analyze(store, cfg.ab_campaign)` passed `ABCampaignConfig \| None` where non-`None` is required | Bound to a local + `assert ... is not None` (the `_config` factory always sets it) so the Optional is narrowed | correctness / typing |
| D | `F_030` `j4._limiter` and `F_021` `sink.render(...)` accessed attributes absent on the `Judge` / `ResultSink` protocols | `assert isinstance(j4, BudgetedJudge)` / `isinstance(sink, HtmlFileSink)` — runtime-checked narrowing (safer than a blind `cast`) to the concrete type | correctness / typing |
| E | `F_018` `{**cfg_base["run"], ...}` — `cfg_base` inferred as a narrow `Collection` type | Annotated `cfg_base: dict[str, Any]` (the dict is heterogeneous by design) | typing |
| F | `tests/test_phoenix_sink.py` — `SimpleNamespace` stand-in passed to `emit(RunResult)`; `sink._client` / `_client.scores/.flushed` absent on the `ResultSink` / `PhoenixScoreClient` protocols | Typed `_run(...) -> RunResult` via one `cast` (fixes every `emit` site at once); added reusable `_phoenix_sink()` / `_null_client()` helpers that narrow to the concrete `PhoenixSink` / `NullPhoenixScoreClient` | reusable helpers / DRY / typing |
| G | `tests/test_phoenix_cli.py` — `captured["pc"].enabled` on `PhoenixConfig \| None` | `assert cfg.phoenix is not None` then assert on the (same) object | typing |

Every fix is behaviour-preserving: `model_validate` ≡ constructor for pydantic; `assert
isinstance`/`is not None` are runtime-checked invariants that already held; the one `cast`
documents a deliberate duck-typed test fake. All 7 touched validation gates still exit `0`
standalone.

## Verification (CI-matching venv)

| Gate | Result |
|---|---|
| `mypy src/eval_harness` / `mypy scripts` / `mypy tests` | green (27 / 56 / 49 files) |
| `ruff check` + `ruff format --check` (`src tests scripts`) | clean (132 files) |
| root `eval_harness` suite | 654 passed, **97.27%** (floor 96%) |
| `--cov=scripts` (mirrors `eval-harness-ci.yml`) | **95.29%** (floor 85%) |
| agent-core / behavioral-regression / flow-corpus / flow-protocol | **98.12 / 98.52 / 99.79 / 100%** (floor 95/96%) |

## Deliberately left unchanged (documented, not oversights)

- **The `phoenix-evals` → numpy 2.5 stub / mypy-under-3.10 limitation** is unchanged and
  remains correctly documented in `[tool.mypy]` (pyproject.toml). CI intentionally omits
  `phoenix-evals` from its install set, so this never gates; no action taken beyond confirming
  the note is still accurate.
- **No `SCHEMA_VERSION` bump, no new runtime dependency, no protected eval-logic change.** The
  edits touch validation *gates* and *tests* (protected paths → the PR carries the
  `eval-change-approved` label) plus the `[tool.mypy]` config; the evaluation logic under
  `src/eval_harness/{gating,scorers,judges}` is untouched.

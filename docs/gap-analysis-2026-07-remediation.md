# Gap-Analysis Remediation Round — 2026-07

A follow-up to [`gap-analysis-2026-07.md`](gap-analysis-2026-07.md). A fresh objective scan
(measurements + an exploration sweep) of the `claude/codebase-production-refactor` branch
re-confirmed the baseline is already healthy — coverage 94–100% everywhere (vs the 85% floor),
`ruff` (now `C901`-clean) and `mypy --strict` green, config versioned with migration chains,
logging present at I/O boundaries. This round closes the **narrow set of genuine residuals** the
scan surfaced, and records what was deliberately left unchanged so the decisions are auditable.

Scope was confirmed with the maintainer: *targeted, high-value fixes only*; *logging only at
true gaps* (keep pure cores log-free by design); no blanket refactor of an already-mature system.

## Fixed this round

| # | Finding (evidence) | Fix | Category |
|---|---|---|---|
| A | Hard-coded sycophancy cutoff `0.5` in `behavioral_regression/generator.py` (`_label_text`, `sycophancy_indicators`) — the one threshold not on `BRConfig` | Added `BRConfig.sycophancy_label_threshold` (named-constant default, validated `[0,1]`), threaded through the generator + `canary`/`pipeline` callers | no hard-coded values / dynamic / backwards-compatible |
| B | Fail-safe subprocess `_run` duplicated & drifted across `agent_core/detectors.py` and `store_sync/git_sync.py` (the git_sync copy had dropped logging) | Extracted `agent_core/subprocess_util.py::run_failsafe`; both bind `_run = run_failsafe` (monkeypatch seam preserved) | DRY / reusable tools |
| B | Atomic write-tmp-then-replace duplicated & drifted across `persistence.py` and `store_sync/store.py` (store.py didn't log the cleanup) | Extracted `agent_core/atomic_io.py::atomic_write_text` (logged cleanup); reused in both | DRY / reusable tools |
| C | `behavioral_regression/cli.py` wrote JSON/HTML reports and produced the ship/hold/escalate decision with **zero logging** | Added INFO logs for run start, each report write, and the decision (via the package's standard `get_logger`) | observability |
| C | `git_sync`/`store` I/O paths lacked logs | Closed for free by the shared utils in (B) | observability |
| D | `validate_skill.check_behavioral` = 71 lines (> 50-line budget), duplicated across 5 vendored copies | Decomposed into `_exec` / `_validate_eval_shape` / `_run_one_eval`; behaviour & messages byte-identical; 5 copies synced. Cleared 5 size-budget warnings (40 → 35) | reusable methods / function length |
| E | `scripts/check_size_budget.py` (this branch's new gate) could crash on an out-of-repo `--root` and didn't exclude in-tree virtualenvs (Copilot review) | Early repo-confinement check → documented exit 2; `.venv`/`venv`/`.tox`/`.nox`/`.eggs` excluded; `_is_excluded` crash-safe | correctness / hardening |
| E | `F_032._read_store_sync_impl` crashed if the `store_sync/` dir were missing; `package_validate.Fail = Any` erased typing (Copilot review) | Guard missing dir → return `""` (clean gate failure); `Fail` is now a typed `Protocol` | correctness / typing |

All fixes ship with tests; every package's coverage floor and `ruff`/`mypy --strict`/format
gates stay green, and the F-032, skill-drift, and architecture-drift guards pass. No
`SCHEMA_VERSION` bump, no new runtime dependency, no protected eval-logic change.

## Deliberately left unchanged (documented, not oversights)

- **Cohesive long functions** (the remaining 35 size-budget *warnings*, ADR 0019). These are
  either one-shot `scripts/validations/F_*.py` `main()`s, argparse entry points, or genuinely
  cohesive pipelines whose length is inherent — e.g. `flow_corpus/validation/runner.py::run_suite`
  (106 lines), where the size comes from two many-field structured-logging calls and a 10-field
  result construction. Forcing these under 50 lines would create data-clump helpers that read
  *worse*, so they remain non-blocking warnings, not hard failures.
- **Pure-core modules stay log-free** (`merge_gate` — documented "pure and deterministic",
  `calibration`, `config`, `golden`'s pure JSONL (de)serialization). Logging belongs at the
  I/O boundary (the CLI / CI wrappers), which do log. Adding logs to pure functions would be
  noise, not observability.
- **Per-gate subprocess timeouts** in `scripts/validations/F_*.py` (literal `600`/`300`/`180`…).
  These live in protected, one-shot CI gate scripts; centralising them is low value and would
  touch the protected eval surface for no functional gain.
- **`eval_harness` `SCHEMA_VERSION = "1.0"`** (two-part vs the three-part semver used by the
  other packages). Cosmetic; changing it touches schema/migration comparison semantics under a
  protected path and is out of scope for a tech-debt pass.

## How to re-measure

```bash
python scripts/check_size_budget.py            # 0 files > 500 lines; 35 warnings (backlog)
ruff check src tests scripts agent-core flow-corpus flow-protocol behavioral-regression
(cd agent-core && mypy agent_core tests)       # strict, clean
# per-package suites (coverage floors: eval_harness 96, others 95, scripts 85):
pytest --cov=eval_harness -q
(cd agent-core && pytest --cov=agent_core -q)
(cd behavioral-regression && pytest --cov=behavioral_regression -q)
pytest tests --cov=scripts --cov-config=scripts/.coveragerc -q
```

# Gap Analysis & Tech-Debt Report — 2026-07

Scope: full branch scan (`src/`, `tests/`, `scripts/`, `skills/`, `agent-core/`,
`behavioral-regression/`, `flow-corpus/`, `flow-protocol/`) with the repo's pinned
toolchain (ruff 0.15.20, mypy 2.1.0, pytest 8, coverage with branch measurement).
Every number below was measured, not estimated.

## 1. Baseline — what is already healthy

| Area | Result |
|---|---|
| `ruff check` / `ruff format --check` on all CI-covered code (`src`, `tests`, subpackage libs, skill libs) | clean |
| `mypy` on `src/eval_harness`, `agent_core`, `behavioral_regression`, `flow_corpus`, `flow_protocol` | clean |
| Root suite (`pytest --cov`) | 501 passed; **97.29%** branch coverage vs `fail_under = 96` |
| `behavioral-regression`, `flow-corpus`, `flow-protocol` suites | 75 / 107 / 17 passed; **100%** coverage each vs gate 95 |
| Skill suites (eval-corpus-forge, architecture-drift-guard, model-bench, openai-judge) | 104 / 91 / 8 / 6 passed (drift-guard requires the pinned `grimp==3.14` extra) |
| Hardcoded secrets / endpoints / model IDs in library code | none found (grep sweep; the only hits are docstring prose) |
| `print()` usage in libraries | not debt on inspection: `ConsoleSink.emit` prints by design; the `agent-core` prints are CLI stdout inside `main()` entry points |
| numpy | not used anywhere; ruff `NPY*` rules have no target (noted so "enable numpy lint" is a conscious no-op) |

Coverage gates already exceed the requested 85% floor everywhere a gate exists
(95–96). The gaps below are the places **outside** those gates.

## 2. Gaps found

### G1 — `scripts/` is un-linted and un-typed by CI (169 ruff findings, 19 mypy errors)

`eval-harness-ci.yml` runs `ruff check src tests` only; no workflow lints or
type-checks `scripts/` (44 Python files). Findings by rule:
E402 ×40 (imports after the deliberate `sys.path` bootstrap in standalone
validation gates), RUF002/001/003 ×46 (typographic characters in docstring
prose), N999 ×30 (feature-gate files deliberately named after feature IDs,
`F_013.py`), W293 ×14, UP045 ×13, UP031 ×11, UP015 ×9, I001 ×7, UP006 ×6,
UP035 ×4, F401 ×2 (dead imports), N811 ×1. mypy: 19 errors in 16 files
(mostly `no-any-return` at yaml/json boundaries).

**Resolution:** fix everything mechanical; add `per-file-ignores` only for the
three deliberate patterns (bootstrap E402, feature-ID N999, prose RUF00x);
type-clean the yaml/json boundaries; add `ruff check scripts` +
`mypy scripts` to CI so the state is enforced, not aspirational.

### G2 — `scripts/` coverage is unmeasured and uneven (aggregate 39%)

`pyproject.toml` omits `*/scripts/*` from coverage, so no gate applies. Measured
with the omit lifted: operational tooling is strong
(`check_skill_script_drift` 98%, `fix_loop` 98%, `check_protected_changes` 97%,
`skill_marketplace` 94%, `regression_gate` 92%) but three operational scripts
are essentially untested: **`validate.py` 16%** (368 lines — the features.yaml
schema/DAG/provenance validator that CI itself runs), **`select_next.py` 0%**
(178 lines), **`init.py` 0%** (131 lines). The `validations/F_*.py` files at 0%
are themselves one-shot CI gates executed via features.yaml validation
commands — tests-of-tests; excluded from the unit-coverage gate by design
(F_020–F_023 are covered where quality-gates.yml measures them directly).

**Resolution:** unit tests for `validate.py`, `select_next.py`, `init.py`;
a dedicated coverage gate for operational scripts at **fail_under = 85**
(excluding `validations/F_*` self-executing gates), wired into CI.

### G3 — `agent_core.detectors.resolve_repo` breaks under git `insteadOf` rewrites

`resolve_repo` shells out to `git remote get-url origin`, which applies the
user's `url.<base>.insteadOf` rewrites. On any machine with such config (SSH
rewrites are common; this remote container rewrites `https://github.com/` to a
local proxy) the parsed URL no longer matches `owner/repo` and detection
silently returns `None` — reproduced here as a real test failure
(`test_resolve_repo_from_https_remote`).

**Resolution:** read the declared remote via `git config --get remote.origin.url`
(raw, rewrite-free) instead. Same signature and return contract — backwards
compatible; the intent is "identify the declared origin", not "identify the
transport URL".

### G4 — vendored `validate_skill.py` copies carry style debt

The canonical `scripts/validate_skill.py` (78% covered, style findings incl.
UP015/UP045) is vendored byte-identically into each skill (ADR 0009, enforced
by `check_skill_script_drift.py`), and each skill's CI deliberately excludes it
from lint. Style fixes therefore must be made in the canonical copy and
re-synced to all four skills in the same change or the drift gate fails.

**Resolution:** apply mechanical fixes to the canonical file, resync copies,
let the existing drift test verify byte-equality.

### G5 — toolchain shadowing (environment observation, not repo debt)

`pip install` honors the ruff/mypy pins, but stale binaries on `PATH`
(`~/.local/bin`) can shadow them and silently lint with a different version —
the exact drift the pins exist to prevent. CI is unaffected. Mitigation for
humans: invoke via `python -m ruff` / `python -m mypy`.

## 3. Explicit non-gaps (checked, no action)

- **Backwards compatibility:** dedicated test files (`test_backwards_compat_cli.py`,
  `test_backwards_compat_config.py`) already pin the public CLI/config surface; all pass.
- **Reusability/DI:** registry + entry-point plugin architecture (`plugins.py`,
  `SINKS.register`, protocol-typed seams) is in place and exercised by tests.
- **Logging:** libraries expose logging; scripts share `scripts/_cli.py::configure_logging`
  (structured, level-controlled). The fixes in G1/G2 keep new/touched scripts on that path.
- **Coverage gates ≥85:** already 95–96 everywhere gated; this report only adds a gate
  where none existed (G2).

## 4. Remediation checklist (this branch)

- [x] G1: mechanical ruff fixes + scoped per-file-ignores; mypy-clean `scripts/`; CI lint/type job for `scripts/`
- [x] G2: tests for `validate.py`, `select_next.py`, `init.py`; scripts coverage gate ≥85 in CI
- [x] G3: `resolve_repo` reads raw remote URL; env-sensitive test now passes everywhere
- [x] G4: canonical `validate_skill.py` style fixes resynced to all vendored copies
- [x] Full verification: ruff + format + mypy + all test suites green with gates enforced

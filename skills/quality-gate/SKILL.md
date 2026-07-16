---
name: quality-gate
description: Generate a deterministic quality-gate shell script (scripts/quality-gate.sh) that runs lint, type-check, tests and a coverage threshold for a Python project, using bash strict mode. Use this whenever the user wants a single command that runs all checks, a CI-and-local quality gate, a pre-merge or pre-commit check script, to enforce a coverage threshold, or to stop lint/test commands drifting between the Makefile and CI. Detects ruff, mypy/pyright, pytest and coverage config and bakes them into one ShellCheck-clean script that CI and `make check` both call.
validator_version: '2.0'
compatibility: python>=3.10 (tomli on 3.10)
version: 1.0.0
---

# quality-gate — gate-script writer

Emit one script — `scripts/quality-gate.sh` — that is the **single source of truth** for a
project's checks. CI and local developers run the *same* script, so the two cannot drift. The
generator inspects the project once; the script it writes runs with zero inference and uses
`set -euo pipefail` so any failing step aborts non-zero.

## 1. Preconditions (input contract)

- A target project directory exists (default: the current directory).
- Optionally `pyproject.toml` and/or config for ruff, mypy/pyright, pytest, and coverage. Only
  the checks that are actually configured are emitted — nothing is fabricated.
- Python 3.10+ (`tomli` on 3.10; 3.11+ uses stdlib `tomllib`).

## 2. Procedure (the E2E steps)

```bash
python scripts/gen_gate.py --root <project> [--out <path>] [--stdout] [--check] [--print-ci]
```

1. **Inspect** the project: ruff, mypy vs pyright (+ paths), pytest, pytest-cov, coverage source
   and `fail_under` threshold.
2. **Emit** `scripts/quality-gate.sh` with strict mode, a `log` helper, one `do_<step>` function
   per supported check, an aggregate `do_all` (which runs coverage instead of a bare test run when
   both exist, so tests never run twice), and a `main` dispatcher for
   `lint | typecheck | test | coverage | all` (default `all`).
3. **Wire CI to the same script** (`--print-ci` prints a ready GitHub Actions step) so CI == local.
4. **Review** and commit. Variables (`PYTHON`, `COVERAGE_SOURCE`, `COV_FAIL_UNDER`,
   `TYPECHECK_PATHS`) are `${VAR:-default}` overridable.

## 3. Output contract (postconditions — what "done" means)

- `scripts/quality-gate.sh` is written (mode `+x`), starts with `#!/usr/bin/env bash`, sets
  `-euo pipefail`, and ends in exactly one newline (LF).
- Re-running on an unchanged project produces a **byte-identical** script (no timestamps).
- `./scripts/quality-gate.sh all` exits 0 when every check passes and non-zero on the first
  failure; an unknown subcommand exits 2.
- ShellCheck-clean: every variable expansion is double-quoted; no variables in printf formats.

## 4. Failure handling

- A missing/malformed `pyproject.toml` degrades to safe defaults. A project with no detectable
  checks yields a valid no-op gate and a stderr warning (rather than a fabricated command).
- `--check` is **advisory** (see §5), never a hard gate.

## 5. `--check` is advisory, not a gate

`--check` exits 1 when the committed script differs from a fresh render — an optional drift signal
for teams who keep the script fully generated. The script is meant to be extended, so do not wire
`--check` into CI as a blocking gate by default. (Wiring `quality-gate.sh` *itself* into CI is the
point — that is what `--print-ci` is for.)

## 6. Validation gate (before declaring success)

You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 7. Examples

**Example 1 — full toolchain**
Input: a project with ruff, mypy, pytest and `[tool.coverage] fail_under = 85`.
Output: a `quality-gate.sh` whose `all` target runs ruff (check + format), mypy, then
`pytest --cov=... --cov-fail-under=85`, printing `PASS` only if every step succeeds.

**Example 2 — CI parity**
`python scripts/gen_gate.py --print-ci` prints a GitHub Actions step whose `run:` is
`./scripts/quality-gate.sh all` — the identical script developers run locally.

---
name: quality-gate
description: Generate a deterministic quality-gate shell script (scripts/quality-gate.sh) that runs lint, type-check, tests and a coverage threshold for a Python project, using bash strict mode. Use this whenever the user wants a single command that runs all checks, a CI-and-local quality gate, a pre-merge or pre-commit check script, to enforce a coverage threshold, or to stop lint/test commands drifting between the Makefile and CI. Detects ruff, mypy/pyright, pytest and coverage config and bakes them into one ShellCheck-clean script that CI and `make check` both call.
validator_version: '2.0'
compatibility: python>=3.10 (tomli on 3.10)
version: 1.2.0
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
python scripts/gen_gate.py --root <project> [--lint-path P]... [--typecheck-path P]... \
    [--out <path>] [--stdout] [--check] [--print-ci]
```

1. **Inspect** the project: ruff, mypy vs pyright (+ paths), pytest, pytest-cov, coverage
   source(s) and `fail_under` threshold. ALL declared `[tool.coverage.run] source` entries are
   kept (rendered as repeated `--cov=` flags) — measuring a subset would weaken the gate.
2. **Explicit paths (optional, repeatable):** `--lint-path` / `--typecheck-path` record facts
   that live outside `pyproject.toml` (e.g. a CI matrix that lints `src tests scripts` and runs
   mypy per-path to avoid module-name collisions). Multiple typecheck paths render one
   invocation each. The exact invocation is embedded as a `# regenerate:` provenance comment,
   so the artifact documents its own reproduction. A `--typecheck-path` without a detected type
   checker — or a `--lint-path` without a detected ruff configuration — is ignored with a
   warning and excluded from the provenance comment: flags cannot fabricate a step.
3. **Emit** `scripts/quality-gate.sh` with strict mode, a `log` helper, one `do_<step>` function
   per supported check, an aggregate `do_all` (which runs coverage instead of a bare test run when
   both exist, so tests never run twice), and a `main` dispatcher for
   `lint | typecheck | test | coverage | all` (default `all`).
4. **Extend by hand below the marker.** Everything above the
   `# --- hand-maintained extensions below ... ---` line is generator-owned; below it is yours
   and survives regeneration. Define `do_extra()` there (before the final `main "$@"` line) and
   `all` runs it automatically — project-specific steps join the gate without the generator
   guessing them.
5. **Wire CI to the same script** (`--print-ci` prints a ready GitHub Actions step) so CI == local.
6. **Review** and commit. `PYTHON` is always `${PYTHON:-default}` overridable. `TYPECHECK_PATHS`
   is `${TYPECHECK_PATHS:-default}` overridable in single-path mode (a documented debug
   affordance for a non-thresholded check); multi-path type-check commands render literal
   (quoted, escaped) arguments instead, with a stderr notice if the env var is set anyway.
   `COVERAGE_SOURCE` and `COV_FAIL_UNDER` are gate-integrity values, not a debug affordance:
   **both are always generation-time literals**, single-source or multi-source alike — never a
   live env override. Setting either at runtime prints an "is ignored" notice to stderr and has
   no other effect. `PYTEST_ADDOPTS` is read natively by pytest, so the coverage and test steps
   additionally warn and `unset` it before invoking pytest — a gate stage has no opt-out.

## 3. Output contract (postconditions — what "done" means)

- `scripts/quality-gate.sh` is written (mode `+x`), starts with `#!/usr/bin/env bash`, sets
  `-euo pipefail`, and ends in exactly one newline (LF).
- Re-running on an unchanged project produces a **byte-identical** script (no timestamps).
- `./scripts/quality-gate.sh all` exits 0 when every check passes and non-zero on the first
  failure; an unknown subcommand exits 2.
- ShellCheck-clean: every variable expansion is double-quoted; no variables in printf formats.
- The coverage threshold cannot be weakened at runtime: `COV_FAIL_UNDER`, `COVERAGE_SOURCE`, and
  `PYTEST_ADDOPTS` set in the environment have **no effect** on `coverage`/`test` — each is
  either baked in as a generation-time literal or explicitly cleared before pytest runs, with a
  stderr notice either way.

## 4. Failure handling

- A missing/malformed `pyproject.toml` degrades to safe defaults. A project with no detectable
  checks yields a valid no-op gate and a stderr warning (rather than a fabricated command).
- `--check` is **advisory** (see §5), never a hard gate.

## 5. `--check` is advisory, not a gate

`--check` exits 1 when the committed script's **generator-owned prefix** (everything above the
hand-extension marker) differs from a fresh render — an optional drift signal. Hand-maintained
content below the marker is never compared and is preserved by regeneration, so extending the
script does not create permanent `--check` noise. Do not wire `--check` into CI as a blocking
gate by default. (Wiring `quality-gate.sh` *itself* into CI is the point — that is what
`--print-ci` is for.)

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

---
name: project-setup
description: Generate a deterministic, self-documenting Makefile for a Python project by detecting its toolchain (ruff, mypy/pyright, pytest, coverage) and package manager. Use this whenever the user wants a Makefile, a `make` build/test/lint interface, one-command project tasks, to scaffold or standardize a repo's developer commands, or to stop re-deriving how to run a project's checks each time. Emits build/test/lint/typecheck/coverage/check targets and delegates to a quality-gate or deploy script when present.
validator_version: '2.0'
compatibility: python>=3.10 (tomli on 3.10)
version: 1.1.0
---

# project-setup — Makefile writer

Turn a Python project's *implicit* toolchain into an *explicit*, committed Makefile so routine
tasks run as one deterministic command (`make test`, `make check`) instead of being re-inferred
each session. Detection is a pure function of the project's files; the emitted Makefile is
byte-stable and safe to extend by hand. **The generator runs the model only once, at generation
time; the Makefile it writes needs zero inference to run thereafter.**

## 1. Preconditions (input contract)

- A target project directory exists (default: the current directory).
- Optionally a `pyproject.toml` and/or marker files (`requirements.txt`, `poetry.lock`,
  `pdm.lock`, `uv.lock`, `pyrightconfig.json`, a `tests/` directory). Detection degrades
  gracefully: absent config just yields fewer targets — nothing is fabricated.
- Python 3.10+ (`tomli` is needed only on 3.10; 3.11+ uses stdlib `tomllib`).

## 2. Procedure (the E2E steps)

Run the deterministic generator; do not hand-write the Makefile.

```bash
python scripts/gen_makefile.py --root <project> [--workspace] [--out <path>] [--stdout] [--check]
```

1. **Inspect** the project: package manager, ruff/mypy/pyright/pytest/coverage config, `src/` vs
   flat layout, the coverage source and `fail_under` threshold, and whether sibling
   `scripts/quality-gate.sh` / `scripts/deploy.sh` already exist.
2. **Emit** a Makefile with `.DEFAULT_GOAL := help`, `.DELETE_ON_ERROR`, `.PHONY` on every phony
   target, `?=` overridable variables, a self-documenting `help` target, and
   `install/format/lint/typecheck/test/coverage/check/build/clean` (plus `deploy`) as detected.
3. **Compose, don't duplicate:** when `scripts/quality-gate.sh` exists the lint/typecheck/test/
   coverage/check targets delegate to it (one source of truth); otherwise they emit the tool
   commands inline so the Makefile stands alone.
4. **Monorepo (`--workspace`, optional):** members are the immediate-child directories with
   their own `pyproject.toml` (a pure, sorted filesystem observation — nested fixture trees
   never match). The root Makefile gains explicit `check-<member>` targets (`$(MAKE) -C
   <member> check`, so each member's tool configs resolve in its own cwd), aggregate
   `check-all` / `install-all` (one sorted `pip install -e ...` line) / `clean-all`, and every
   member gets its own single-package Makefile. `--check` then iterates ALL artifacts.
   Environment variables (e.g. `HYPOTHESIS_PROFILE`) propagate through `$(MAKE) -C` untouched.
5. **Review** the generated files with the user and commit them. They are scaffolds — extend freely.

## 3. Output contract (postconditions — what "done" means)

- A Makefile is written at `--out` (default `<root>/Makefile`), ending in exactly one newline,
  with LF line endings and **hard-TAB-indented recipes** (Make rejects spaces).
- Re-running on an unchanged project produces a **byte-identical** file (no timestamps).
- `make help` lists the available targets; `make check` runs the aggregate quality gate.
- Targets POSIX/GNU make (Linux, macOS, WSL).

## 4. Failure handling

- A missing or malformed `pyproject.toml` is not an error: detection returns safe defaults and the
  Makefile still emits `help`, `install`, and `clean`.
- `--check` is **advisory** (see §5), never a hard gate — the Makefile is meant to be edited.

## 5. `--check` is advisory, not a gate

`--check` exits 1 when the committed Makefile differs from a fresh render — useful as an *optional*
drift signal for teams who choose to keep the file fully generated. Because the Makefile is a
scaffold users extend, **do not** wire `--check` into CI as a blocking gate by default.

## 6. Validation gate (before declaring success)

You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 7. Examples

**Example 1 — src-layout pip project**
Input: a project with `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`,
`[tool.coverage]`, and `src/`.
Output: a Makefile whose `typecheck` runs `mypy src`, whose `coverage` enforces the detected
`--cov-fail-under`, and whose `check` chains `lint typecheck test`.

**Example 2 — delegation**
Input: a project that already has `scripts/quality-gate.sh`.
Output: a Makefile whose `check` target is `./scripts/quality-gate.sh all` (no duplicated commands).

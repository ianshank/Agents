# 0019 — Structural size-budget enforcement (complexity, file/function length)

- Status: **Accepted.**
- Date: 2026-07-05
- Related: `scripts/check_size_budget.py`, `.github/workflows/quality-gates.yml`,
  ADR 0009 (uniform coverage floor + compat surface).

## Context

The project's contributing standards document four structural limits:

| Limit | Value |
|---|---|
| Cyclomatic complexity per function | < 15 |
| Source file length | ≤ 500 lines |
| Function length | ≤ 50 lines |
| Public methods per class | ≤ 15 |

Until now none of these were **enforced** — they were prose, not gates. An audit found the
limits had already drifted: `agent_core/store_sync.py` was 546 lines, and two functions
(`behavioral_regression.config.__post_init__` = 18, `scripts/validate_skill.check_structural`
= 15, plus two more in `eval-corpus-forge`) exceeded the complexity budget. Nothing stopped
further drift.

## Decision

Enforce the two limits that can be gated cleanly and green, and track the other two as
non-blocking, visible warnings rather than silently dropping them.

### 1. Cyclomatic complexity < 15 — HARD, via ruff `C901`

`C901` is added to `[tool.ruff.lint] select` with `[tool.ruff.lint.mccabe] max-complexity = 14`
(the highest *allowed* value, so anything ≥ 15 fails) in the root `pyproject.toml` and every
sub-package config. Skills inherit it: their `ruff.toml` files `extend` the root config (and
`eval-corpus-forge` resolves it by upward search). The four pre-existing violations were
refactored — each by extracting single-responsibility helpers — with behaviour and error
messages preserved byte-for-byte. Enforced by the existing per-package `ruff check` CI steps;
no new workflow wiring needed.

### 2. File length ≤ 500 — HARD, via `scripts/check_size_budget.py`

ruff has no native file-length rule, so a small stdlib gate walks the source tree
(excluding `tests/`, caches, fixtures, virtualenvs) and fails (exit 1) on any `*.py` over
`MAX_FILE_LINES = 500`. The one violation (`store_sync.py`) was split into a
backwards-compatible package. Wired into `quality-gates.yml`; the gate has its own unit
tests under the ≥ 85% `scripts/` coverage floor.

### 3. Function length ≤ 50 and public methods ≤ 15 — NON-BLOCKING warnings

Measured but not gated. Rationale:

- **Function length**: 41 functions currently exceed 50 physical lines — mostly argparse
  `main()` bodies and one-shot `scripts/validations/F_*.py` gates where the length is
  inherent, plus several in protected paths (`scripts/validations/`, `tests/`).
  Hard-gating would force ~41 refactors across the eval-integrity surface — high risk,
  low value, and contrary to the "maintain a working state, don't churn a mature codebase"
  principle. `check_size_budget.py` prints each overage as `[warn] function_lines: …` so the
  backlog is visible and never silently truncated.
- **Public methods ≤ 15**: ruff's `PLR0904` requires preview/unstable mode; enforcing an
  unstable rule in CI is itself a drift risk. The custom gate reports overages as warnings
  using stable AST inspection instead.

Both warning classes are surfaced on every CI run and can be promoted to hard gates once the
backlog is burned down.

## Consequences

- Complexity and file-size can no longer regress silently; the two clean metrics are green
  today and stay green.
- The function-length backlog is documented and observable rather than hidden. Promotion to
  a hard gate is a config change (`hard=True`) plus the refactors.
- The gate dogfoods its own budgets (its functions stay under the complexity and length
  limits) and carries the same ≥ 85% coverage floor as the rest of `scripts/`.

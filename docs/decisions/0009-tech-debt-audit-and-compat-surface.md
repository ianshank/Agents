# 0009 — Tech-debt audit, intentional compatibility surface, and uniform 95% coverage

- Status: **Accepted**
- Date: 2026-06-29
- Related: `scripts/_cli.py`, `scripts/check_skill_script_drift.py`,
  `.github/workflows/quality-gates.yml`, `.github/workflows/skills-ci.yml`

## Context

A tech-debt sweep was requested: reduce debt, keep CI green, scan for hard-coded values /
dead / redundant code, and reach 95% coverage. The audit found that most of those goals
were **already met**, so this ADR records the findings (so they are not re-investigated)
and the small set of changes that were genuinely worth making.

### Audit findings (baseline — no change required)

- **CI is green** on `main` across every workflow; `ruff check` + `ruff format --check`
  pass at the repo root and in all four packages.
- **Coverage gates already pass.** Root/`eval_harness` enforces `fail_under = 96`; the
  `agent-core`, `flow-protocol`, `flow-corpus`, and `behavioral-regression` packages
  enforce 95%.
- **No hard-coded secrets, absolute paths, or production URLs** exist in source. Judge
  credentials are read from the environment; model ids and endpoints come from config.
  The `AnthropicJudge` default model (`claude-opus-4-8`) is an explicit, config-overridable
  default — never hard-coded at a call site (see its docstring).

## Decision

### 1. Intentional backwards-compatibility surface (kept, documented)

These shims are deliberate. They are **retained**, covered by tests, and must not be
removed without a separate, reviewed deprecation:

- **`ece` alias** for `expected_calibration_error` in `agent-core/agent_core/__init__.py`
  (emits `DeprecationWarning`; covered by `agent-core/tests/test_backwards_compat.py`).
- **Pre-3.10 entry-point shim** in `src/eval_harness/plugins.py` (`# pragma: no cover`).
- **Config-schema migrations**: `src/eval_harness/config/migrations.py` (0.9 → 1.0) and
  `agent-core/agent_core/version.py` (1.0 → 1.3). They let older on-disk configs load
  unchanged and are the compatibility contract for existing users.

### 2. By-design duplication, now drift-checked (not de-duplicated)

`scripts/validate_skill.py` is intentionally **copied** into each skill
(`skills/*/scripts/validate_skill.py`) so a skill stays self-contained and independently
vendorable. De-duplicating it would break that portability. Instead, the repo-root copy is
designated **canonical** and a new guard, `scripts/check_skill_script_drift.py`, fails CI
if any vendored copy diverges (it compares SHA-256 digests; new duplications are added to
its declarative `TRACKED_DUPLICATES` map). This is especially important for the
`openai-judge` skill, which has no CI job of its own — the drift guard is the only thing
that would catch divergence there. It runs in `quality-gates.yml`.

### 3. Reusable CLI logging helper (removed duplication)

The five repo-root tooling scripts each duplicated the same `logging.basicConfig(...)`
block. That single convention now lives in `scripts/_cli.py` as `configure_logging()`,
imported by `validate.py`, `regression_gate.py`, `select_next.py`, `init.py`, and
`check_protected_changes.py`. A dead `_venv_pip` helper (and its only, unused caller) in
`scripts/init.py` was removed.

### 4. Uniform 95% coverage floor

The two skills (`eval-corpus-forge`, `architecture-drift-guard`) had a 90% gate while the
core packages were at ≥95%. Both skills were already above 95% in practice; their gates in
`skills-ci.yml` are raised to **95%** and margin tests were added for the previously
uncovered validation/interpolation branches (forge 98%, adguard 100%).

The **quality-gate tooling** coverage stays at **85%** by design. That set
(`regression_gate.py`, `check_protected_changes.py`, `fix_loop.py`, …) is dominated by
`git worktree` / subprocess orchestration whose error paths are impractical to exercise
without brittle mocking; 85% is the honest floor. The new `_cli.py` and
`check_skill_script_drift.py` modules are added to that job's measured set (both are
near-100% covered).

## Consequences

- **Positive:** Future divergence of vendored skill scripts is caught automatically; the
  logging convention has one definition; the coverage floor is uniform (95%) for libraries
  and skills.
- **Positive:** The compatibility surface is explicit, so it is not mistaken for debt and
  removed by accident.
- **Negative / note:** Because this PR touches protected paths (`tests/**`, `.github/**`,
  and—if judges are edited—`src/eval_harness/judges/**`), it requires the human
  `eval-change-approved` label and CODEOWNERS review per the protected-path guard. That is
  the intended control, not a regression.

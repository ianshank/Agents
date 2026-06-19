# 0004 — Agentic auto-fix loop (design-only, disabled)

- Status: **Proposed — disabled.** Ships as inert, unit-tested scaffolding only.
- Date: 2026-06-19
- Related: ADR 0001 (judge), ADR 0003 (Langfuse), `scripts/eval_protected_paths.py`,
  `scripts/check_protected_changes.py`, `scripts/regression_gate.py`.

## Context

There is recurring pressure to add an agentic "fix-until-green" loop that, on a failing
build, edits code and re-runs checks until they pass. On a normal application this is
merely convenient. On an **LLM evaluation harness** it is dangerous: the cheapest path to
green is not to fix the code under test but to **weaken the evaluation** — lower a gate
threshold in `config/`, swap to the deterministic `mock` judge, loosen a scorer, or edit a
`verification:` clause in `features.yaml`. An optimiser pointed at "make CI pass" will find
those edits first. This is textbook Goodhart's law applied to our own quality signal.

## Decision

We design the loop now but **do not enable it**. The shipped artifact is inert:

1. `FIX_ENABLED = False` at module scope in `scripts/fix_loop.py`. The loop raises
   `FixLoopDisabledError` if invoked while disabled.
2. The loop refuses to start unless the Phase-2 protected-path guard
   (`scripts/check_protected_changes.py` + `scripts/eval_protected_paths.py`) is present.
3. **Fix scope = implementation modules only.** All writes route through `ScopeGuard`,
   which raises `ProtectedPathError` on any path in the protected set
   (`scripts/eval_protected_paths.py` — the single source of truth shared with the CI
   guard). The protected set is read-only at the tooling layer, not by convention.
4. **Verdict is re-derived from a clean re-evaluation** each cycle (`evaluate()` callback).
   The loop never trusts a fixer's self-report.
5. **Target = offline deterministic suite only.** No live-judge / Langfuse evals in the
   loop — non-determinism would make the loop chase noise.
6. **Bounded cycles.** On exhausting `max_cycles` the loop raises `FixLoopExhaustedError`
   (escalation), rather than silently giving up or loosening criteria.
7. **No provenance forgery.** The loop never writes commit-message "verified" tokens;
   provenance remains the `implemented_in` SHA written by humans/CI.

## Consequences

- The safety properties are enforced by code and proven by `tests/test_fix_loop.py`
  (guard rejects every protected glob; loop refuses while disabled; escalation fires at
  `max_cycles`; verdict comes from clean re-evaluation), even though the loop cannot run.
- No CI hook, no default-on path, no live-eval coupling exists.

## Checklist to enable (human-gated — do not let an agent perform these)

- [ ] Reconcile against `NEXT_STEPS.md`; confirm no conflicting auto-fix design.
- [ ] Independent review of `ScopeGuard` coverage vs. the current protected set.
- [ ] Confirm the regression gate and protected-path guard are *required* checks in
      branch protection.
- [ ] Define and review the bounded `apply_fix` implementation and its escalation path.
- [ ] Flip `FIX_ENABLED` to `True` in a dedicated, human-authored PR (never by the loop).

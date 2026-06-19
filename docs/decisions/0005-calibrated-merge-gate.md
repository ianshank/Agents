# 0005 — Calibrated auto-merge gate (opt-in, default-off)

- Status: **Proposed — default-off.** Ships as a pure, unit-tested subsystem plus an
  opt-in CI workflow that auto-merges nothing unless a repo variable is explicitly set.
- Date: 2026-06-19
- Related: ADR 0004 (auto-fix loop), `scripts/eval_protected_paths.py`,
  `scripts/check_protected_changes.py`, `scripts/regression_gate.py`,
  `agent_core/calibration.py`.

## Context

There is recurring pressure to let agent-authored changes merge without a human in the
loop. Blanket auto-merge is unsafe on an evaluation harness for the same Goodhart reason as
the auto-fix loop (ADR 0004): the cheapest path to "merge" must never run through weakening
the apparatus that measures quality. But a *calibrated* gate — one that merges only when a
domain's historical, **human-audited** confidence has earned it — can remove human review
from low-risk product changes while keeping every safety invariant.

## Decision

Ship the decision logic and supporting stores now; keep auto-merge **off by default**.

1. **Mechanical checks are ground truth.** A failed regression gate is an unconditional
   `REJECT`. Calibration buys skipping *human review*, never skipping tests.
2. **Protected (eval-defining) paths never auto-merge.** `decide()` returns `ESCALATE` for
   any change touching the protected set; `protected_auto_merge` defaults `False`.
3. **The threshold is risk-derived, never hardcoded.** `tau` comes from the selective-risk
   curve via a Wilson upper bound on the held-out fold (`threshold_for_risk`), honouring a
   human-set `risk_target` (default 2%).
4. **Only HUMAN_AUDIT labels feed `tau`/health.** Passive labels (revert / CI-failure /
   timeout-clean from `outcome_labeller.py`) drive alerting only; they are biased optimistic
   (timeout-clean cannot see silent errors) and must never raise the auto-merge ceiling.
   Audit labels come from an **unbiased random sample** (`audit_sampler.py`).
5. **Trust requires calibrator health.** Auto-merge needs enough samples, low ECE, an AUROC
   that rank-orders correctness, and a tight upper-bin CI — plus a per-decision Wilson floor
   so a high point-estimate on a thin bin cannot merge.
6. **Cold start escalates.** With no/young audit data a domain has no `tau` and every change
   `ESCALATE`s; autonomy is earned per domain as unbiased labels accumulate.
7. **Decisions are auditable.** `merge_gate_ci.py --audit-log` persists every decision
   (decision, p, tau, health, bin) as JSONL.

## Sample-size note (honest limitation)

`tau` is measured on a **held-out** fold (half the audits) to avoid overfitting the
threshold. At `risk_target = 0.02`, an all-correct operating bin needs ≈190 held-out
samples for its Wilson lower bound to clear 0.98 — so a domain needs roughly several
hundred audited changes in the operating band before it can auto-merge at all. This is
intentional conservatism: the default is to escalate, and the data requirement is the price
of the risk guarantee. Tuning `min_calibration_n` / `risk_target` is a human decision.

## Seam (must be wired by the enabling change)

Nothing here writes the *initial* pending `OutcomeRecord` at merge time. The enabling
workflow must seed `change_id / domain / raw_confidence / merged_at` so the labeller and
audit sampler have records to resolve.

## Consequences

- The subsystem is pure and proven by `agent-core/tests/test_merge_gate*.py`,
  `test_outcome_store.py`, `test_outcome_labeller.py`, `test_audit_sampler.py`.
- `.github/workflows/calibrated-merge-gate.yml` is **skipped entirely** unless
  `vars.ENABLE_CALIBRATED_AUTOMERGE == 'true'` (a job-level `if`), so it never fails PRs by
  default. When enabled it runs the gate, fails on `REJECT`, and only enables GitHub
  auto-merge on `AUTO_MERGE`. Enabling also requires wiring the real upstream inputs
  (mech_pass / touches_protected / raw_confidence / domain) and a populated store.
- Once wired to merge, the gate is itself eval-defining infra and lives under the protected
  set.

## Checklist to enable (human-gated — do not let an agent perform these)

- [ ] Independent review of the decision layers and the protected-path classification feed.
- [ ] Confirm the regression gate and protected-path guard are *required* branch-protection
      checks (mechanical ground truth must hold before the gate is consulted).
- [ ] Implement the merge-time record seeding and the audit-sampling cadence.
- [ ] Accumulate enough HUMAN_AUDIT labels per domain to leave cold start.
- [ ] Set `ENABLE_CALIBRATED_AUTOMERGE=true` in a dedicated, human-authored change.

# 0005 — Calibrated auto-merge gate (opt-in, default-off)

- Status: **Proposed — default-off.** Ships as a pure, unit-tested subsystem plus an
  opt-in CI workflow that auto-merges nothing unless a repo variable is explicitly set.
- Date: 2026-06-19
- Related: ADR 0004 (auto-fix loop), `scripts/eval_protected_paths.py`,
  `scripts/check_protected_changes.py`, `scripts/regression_gate.py`,
  `agent_core/calibration.py`, `agent_core/merge_seed.py` (record seeding, Session 006).

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

## Seam — CLOSED (2026-06-30, Session 006)

The passive **detectors are wired** (`agent_core/detectors.py`): reverts come from `git log`
(the `This reverts commit <sha>` footer) and CI failures from a commit's GitHub Actions
check-runs (`gh api`), both timeout-bounded and failing *safe* (missing binary / timeout / no
repo → no signal).

**Record seeding is now implemented** in `agent_core/merge_seed.py`
(`seed_pending` + a `python -m agent_core.merge_seed` CLI). It writes the *initial* pending
`OutcomeRecord` (`change_id / domain / raw_confidence / merged_at`, `label=None`) at merge
time so the labeller and audit sampler have records to resolve — without it, every domain
stayed in cold-start `ESCALATE` forever because `record_verdict` raises `KeyError` for an
unknown `change_id` and `build_domain_models` never saw any HUMAN_AUDIT rows. Properties that
keep it safe:

- **Inert.** A pending record changes no gate decision (the gate reads HUMAN_AUDIT rows only),
  so seeding cannot move `tau` or health.
- **Idempotent.** A `change_id` already in the store is never re-seeded (workflow retries are
  no-ops).
- **Default-off integration.** `merge_gate_ci.py` seeds only when `--seed-store` *and*
  `--change-id` are passed *and* the decision is `AUTO_MERGE`; absent those flags its behaviour
  is byte-identical. The standalone CLI can also seed human-merged changes.

## Audit-label accumulation strategy

`audit_sampler.py` already selects an **unbiased** sample (Bernoulli `base_rate`, default 5%,
with a per-domain floor, default 30) and records HUMAN_AUDIT verdicts; all of these live on
`AuditConfig` / `GatePolicyConfig` (no hard-coded values). The operating policy to leave cold
start, per domain:

- **Cadence.** Run `python -m agent_core.outcome_labeller` and `audit_sampler select` on a
  fixed schedule (e.g. weekly) over the seeded store; the maturity window
  (`LabellerConfig.maturity_days`, default 7) gates passive labels.
- **Domain scope.** Sample is **stratified by domain** so low-volume domains still reach the
  `per_domain_floor`; a domain leaves cold start only once its held-out audited count clears
  the risk-derived sample-size note above (~several hundred in the operating band at
  `risk_target = 0.02`).
- **Reviewer assignment.** HUMAN_AUDIT verdicts are authoritative and must come from a human
  (CODEOWNERS for the domain), recorded via `audit_sampler record --change-id … --correct/…`.
  Agents must not record audit verdicts.
- **Exit criterion.** Activation stays gated on the checklist below; seeding + cadence are
  necessary but not sufficient — health floors (`min_calibration_n`, `max_ece`, `min_auroc`,
  `max_bin_ci_width`) must also pass on the held-out fold before any domain earns a `tau`.

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
- [x] Implement the merge-time record seeding (`agent_core/merge_seed.py`, Session 006) and
      define the audit-sampling cadence (see "Audit-label accumulation strategy" above).
- [ ] Accumulate enough HUMAN_AUDIT labels per domain to leave cold start.
- [ ] Set `ENABLE_CALIBRATED_AUTOMERGE=true` in a dedicated, human-authored change.

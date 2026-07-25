# Peer Review — "Swap Wilson → PPI++" Estimator Critique (2026-07-25)

**Reviewed artifact:** an external statistical critique of the merge-gate calibration
subsystem (recommends: swap the Wilson interval for PPI++; redefine the N≥20 soak target;
log audit-selection propensity; and a stacked follow-on of multi-task PPI, active/robust
sampling, stratified PPI, judge-noise-aware intervals, and cross-cell shrinkage). Supplied
inline; never committed to this repo.

**Method:** read-only verification against the working tree at
`0b6592d` (branch `claude/openspec-agents-eval-plan-b3xti0`), full reads of
`agent-core/agent_core/{merge_gate,calibration,outcome_store,audit_sampler,calibration_report}.py`
and `docs/plans/agent-record-decontamination/PLAN.md`; independent recomputation of the
Wilson and PPI arithmetic; and a web check of every load-bearing citation. Verdicts are
CONFIRMED / PARTIALLY TRUE / REFUTED with `file:line` or a reproducible computation.

**Outcome:** the surviving, reprioritized recommendations are carried into
`proposal.md` + `design.md` + `tasks.md` in this directory. The critique's *direction* is
adopted; its *ordering* is inverted (proxy measurement first, estimator swap third).

---

## Verdict

Right family of ideas, sound mathematics, real and accurately-summarized citations — but
wrong on **target, magnitude, and mechanism**, and the highest-leverage move is one the
critique only gestures at. (1) The headline "your N≥20 soak can't support a CI-lower-bound
gate" refutes a claim the roadmap **explicitly disclaims**: tau/auto-merge enablement is a
stated non-goal and the plan already prints "at n≈12 audited records, Wilson half-widths
are ≈±0.2-0.3 — a baseline, not a verdict". (2) The real activation bar is not one N≥20
gate but a **stack of four Wilson gates**, the worst of which needs **~380 near-perfect
audited records per domain** for `tau` to even exist. (3) PPI++ on the *natural* proxy (the
calibrated confidence) buys only **~1.05–1.1× effective-N** at the system's own
`min_auroc=0.65` floor, and structurally **~0** on the range-restricted subsets the gate
conditions on. The lever that matters is the **proxy** — the passive REVERT/CI labels
already on the full merge stream, or an independent LLM judge — which the critique names
("the agreement rate is the gain") but does not center. The three concrete asks are worth
doing; reordered, they become a real plan.

## Findings that change execution

1. **The premise attacks a disclaimed non-goal — REFUTED as stated.**
   `docs/plans/agent-record-decontamination/PLAN.md:15-18` lists as a **Non-goal**: "tau
   enablement / auto-merge activation (`min_calibration_n=200` and the ADR 0005 checklist
   untouched)". Phase 0 is a *reporting* milestone (`:43-45`); Phase 3 commits the honesty
   statement verbatim (`:132-137`); the live store holds **0 `human_audit` records ⇒ tau
   `None` everywhere** (`:37-39`). "The arithmetic kills the premise" refutes a premise the
   team already concedes — the gate is deliberately off and pre-data.

2. **Magnitude: the bar is a four-gate Wilson stack, not one N≥20 gate — the critique
   understates it ~6× (new finding).** From `merge_gate.py` + `outcome_store.py`:
   - **Gate 1 — `tau` exists** (`merge_gate.py:111-133`): `threshold_for_risk` requires the
     kept-set Wilson-lower accuracy ≥ `1 − risk_target = 0.98`, evaluated on the **held-out
     fold** (`outcome_store.py:241-242,265`). Closed form for an all-correct set,
     `wilson_lb(n,n)=n/(n+z²)`, clears 0.98 at **n ≥ 188 in the eval fold ⇒ ~380 total
     audits, ~all correct** (≥650 at 1% error; effectively unreachable at 2%).
   - **Gate 2 — per-bin Wilson floor** (`merge_gate.py:170-171`, `wilson_floor=0.90`):
     operating bin needs ≥ 35 all-correct.
   - **Gate 3 — `bin_ci_width ≤ 0.20`** health (`outcome_store.py:172-186,263`).
   - **Gate 4 — `n ≥ min_calibration_n=200`** health (`merge_gate.py:47,64-70`).
   Net: auto-merge is unreachable until a domain has ~380 near-perfect audits — versus 0
   today, 10–15 targeted next. The instinct is right; the "N≥20" framing is off by ~6×.

3. **Part of the bar is *policy*, not statistics — the 0.98/0.90 targets are tunable
   (PARTIALLY TRUE that it's an estimator problem).** `risk_target` and `wilson_floor` are
   `GatePolicyConfig` fields (`merge_gate.py:44,52`). At `risk_target=0.05`, Gate 1 needs
   ~146 audits, not ~380. Two independent levers the critique fuses into one: a
   **risk-appetite** decision (revisit the targets — cheap, an ADR, no math) and a
   **variance-reduction** decision (PPI++). Treating 0.98 as fixed is a modeling choice, not
   a given.

4. **PPI++ on the confidence proxy is right-direction, insufficient-magnitude — REFUTES
   "top leverage".** PPI/PPI++ shrink a *mean's* variance by ≈ `(1 − ρ²)`
   (`ρ = corr(proxy, correctness)`), so `n_eff/n ≈ 1/(1 − ρ²)`. At the system's own
   `min_auroc=0.65` floor, ρ≈0.25–0.35 ⇒ **~1.05–1.1×** — it does not bridge n≈12 → ~380.
   Worse, the gate's binding quantities are *conditional* (`E[correct | score ≥ tau]`,
   `E[correct | bin]`); on those subsets the confidence proxy is near-constant *by
   construction* (that is what defines a high-score set / one bin), so within-subset ρ→0 and
   PPI++'s gain →0 **exactly where the gate needs it**. PPI++ helps the *unconditional*
   report estimates (base rate, overall agreement) — useful for Phase 3 — not the
   conditional activation gates.

5. **The real lever is the proxy — the critique's own point, uncentered (reframing).**
   Meaningful borrowing needs a proxy with conditional variance on the gated subset that
   correlates with correctness. Two exist already on the **full** merge stream: the passive
   **REVERT / CI_FAILURE / TIMEOUT_CLEAN** labels (`outcome_store.py:33-37`, written on every
   merge by the labeller) and an **independent LLM judge** over the diff (`eval_harness`
   `anthropic`/`openai` judges, or `behavioral-regression`'s `SyntheticJudge`). Measuring
   `ρ(proxy, HUMAN_AUDIT)` — marginal and **conditional** — is computable today from the
   store already held, and is the number that decides whether any PPI work is worth wiring.
   This is the actual first deliverable.

## Wrong emphasis / claims that would have propagated

6. **"A biased audit habit silently breaks the rectifier, invisible until the gate
   confidently passes something" — PARTIALLY TRUE; over-described for the current sampler.**
   `select_for_audit` is content-**blind** (`audit_sampler.py:35-37`, `SystemRandom`) with a
   `per_domain_floor=30` that dominates at today's N (roadmap Phase 2: "the floor dominates
   the 5% rate"). The inclusion probability is a **known, domain-round constant**
   `p = k/N + (1 − k/N)·base_rate` — reconstructible, not silently broken. Logging it is
   still worth it (an HT `1/p` weight corrects the floor's mild over-sampling of low-volume
   domains, and it is the prerequisite for the *active* sampling the critique later
   proposes), but the alarm does not describe the shipped sampler.

7. **"Paired by construction — every audited record carries a mechanical label" — REFUTED on
   shape.** `OutcomeRecord` holds **one** `label` + **one** `label_source`
   (`outcome_store.py:40-52`); proxy↔truth is a **join on `change_id`** across append-only
   records, resolved with HUMAN_AUDIT-wins (`outcome_store.py:108-120`). The report already
   does exactly this join (`calibration_report.py:19-21`). The PPI pair is constructible —
   but it is a join, not a single-row read, which matters for whoever builds the rectifier.

8. **"Your isotonic PAV calibrator is the nonlinear recalibrator the gate uses" — PARTIALLY
   TRUE.** `IsotonicCalibrator` (PAV) is real and the config default (`calibration.py:228`,
   `config.py default_calibrator="isotonic"`), but `decide()` scores the operating point via
   the histogram `BinningCalibrator` (`outcome_store.py:123-169,244`). Binning is
   load-bearing: Gate 2 needs per-bin counts for its Wilson floor, which isotonic does not
   provide. The multi-task-PPI bridge therefore applies to the report/isotonic path, not the
   gate operating point.

9. **"Verified sibling Strategos; one estimator upgrade lands in both repos" — REFUTED as
   stated.** `Strategos-MCTS` appears once, as a **deferred** future consumer gated on its
   own M5 benchmark (`docs/plans/agents-critical-path/PLAN.md:88`); there is no `policy_lift`
   symbol or Strategos code in this repo. The cross-repo benefit is not bankable here.

10. **"Must clear 0.89" — factual drift.** The per-bin constant is `wilson_floor=0.90`
    (`merge_gate.py:52`); the `tau` path needs `acc_lower ≥ 0.98` (`risk_target=0.02`). The
    real targets are slightly *harder* than the critique's 0.89.

11. **`[Certain]`/`[Likely]` evidence tags are not a convention here.** Zero occurrences
    repo-wide; house verdicts are CONFIRMED / PARTIALLY TRUE / REFUTED with `file:line`
    (`docs/plans/agent-record-decontamination/REVIEW.md:97-99`). Cosmetic, noted for
    consistency.

## Claims confirmed accurate

- **The Wilson arithmetic is exact.** 20/20→0.839, 19/20→0.764, 18/20→0.699; the 95%-pass
  crossover for LB≥0.89 is n≈105 ("~100" is fair). Recomputed independently.
- **The citations are real and accurately summarized.** PPI++ = arXiv:2311.01453
  (Angelopoulos, Duchi, Zrnic; power-tuning interpolates classical↔PPI, "no worse
  asymptotically"); Active Statistical Inference = arXiv:2403.03208 (Zrnic & Candès; budget
  to uncertain points, ~80% label savings); Multi-task PPI = arXiv:2605.29249, including the
  quoted theorem ("efficiency gains beyond power-tuned PPI are only possible when the
  proxy–ground-truth relationship contains nonlinear structure; affine cross-task
  recalibrations are asymptotically equivalent to the raw proxy"). CRC (2208.02814) and
  Learn-Then-Test (2110.01052) are canonical.
- **No PPI/rectifier/control-variate machinery exists in-repo** (zero matches); every
  interval is a plain Wilson score interval (`calibration.py:56-65`).
- **Audit-selection propensity is genuinely not logged** — `OutcomeRecord` has no such
  field and `record_verdict` writes none (`audit_sampler.py:61-78`).
- **The estimator swap is feasible via the existing seam** — `ReportConfig` already threads
  `n_bins/risk_target/z` into `analyze_slice` (`calibration_report.py:54-74,95-130`), so an
  `estimator` field follows the same path.
- **The finite-sample caveat the critique raises against active sampling ("start
  interpolated") is correct** and applies to PPI++ itself: at n≈12 the power-tuning λ is
  estimated from the same tiny labeled set and is high-variance, so clamp λ∈[0,1] (PPI++'s
  own guard) and prefer the classical estimator when uncertain.

## Reprioritized recommendations (carried into the proposal)

1. **Measure conditional `ρ(proxy, HUMAN_AUDIT)`** for the passive-label and LLM-judge
   proxies — the number that governs whether any PPI work pays off (WS-A).
2. **Log audit-selection propensity now** — cheap, and irreversible-if-skipped once active
   sampling arrives (WS-B).
3. **Dual-report `--estimator {wilson, ppi++}`** for the aggregate report, honestly scoped
   to unconditional estimates (WS-C).
4. **A separate risk-appetite ADR** on `risk_target`/`wilson_floor` — a policy lever the
   critique fuses with the estimator.
5. **Multi-task PPI / active / stratified / shrinkage — deferred** until ≥3 populated cells
   and a measured ρ exist.

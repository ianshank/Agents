# Peer Review — Agent-Record Calibration Plan (v2, 2026-07-24)

**Reviewed artifact:** `PLAN.md` v2 (`PLAN-2026-07-24-agent-record-decontamination-v2`),
merged in PR #80 on 2026-07-25.
**Method:** re-verification against `origin/main` at `f565e08` (82 commits after the plan
landed) and the live store at `merge-gate-data` `4c07d7e`, measured 2026-08-06. Every
falsifiable claim classified CONFIRMED / PARTIALLY TRUE / REFUTED with file:line.
**Outcome:** the corrected plan is `PLAN.md` in this directory (v3). v2 is superseded.

**Note on authorship.** v2 is this reviewer's own work. That is a reason to apply the
standard more carefully, not less; the first finding below is a rule v2 states and then
breaks in the same document, which is the kind of error self-review most reliably misses.

## Verdict

The phase *spine* holds — one phase is confirmed still-valid and untouched, and the blocker
v2 identified is still the blocker. But v2 is no longer executable as written. Its Phase 0
rests on a lever that events have removed, its milestone has been settled more rigorously by
a later ADR, one of its components never existed under the name it uses, and every file:line
in its standards table has moved. Most of this is drift, which the plan's own "re-measure at
every phase start" rule anticipated and caught. One item is not drift but an authoring
error.

## Findings that would break execution

1. **v2 breaks its own ID-assignment rule inside the same document — REFUTED.** Its
   cross-cutting table states IDs are "never reserved in plans — every ID the 07-03 plan
   pre-assigned (F-038/F-039/F-040, ADR 0019/0020) drifted or gapped." It then reserves
   **ADR 0026** in the header, the Scope line, the Phase 0 heading, three Phase 0 bullets,
   Phase 1 item 3, the Sequencing block, the risk register and the Files list. ADR 0026 was
   claimed the next day by an unrelated decision (proxy-correlation + PPI++). The rule was
   right and the plan violated it within twenty-four hours — the sharpest available
   illustration of why the rule exists. Next free is **0032** (`docs/decisions/` runs to
   0031).

2. **Phase 0's central lever is obsolete — REFUTED.** v2: the backfill "converts the ~18
   historical Claude-authored `human/*` rows to agent domains, taking the agent-domain count
   from ≈5 to ≈23." Measured today: **24 agent-domain rows across 15 change_ids**, reached
   organically. The milestone it was aimed at is already met without it. The backfill also
   cannot supply what is actually missing — agent rows carry `timeout_clean` only (9 labelled,
   15 pending) and the store holds **zero `human_audit`** — because it re-attributes domains
   and creates no labels.

3. **Phase 0's milestone is subsumed, and understated — PARTIALLY TRUE.** ADR 0026 reframed
   N≥20 as "a **soak counter**, not a decision gate", and derived the operative bar: roughly
   **380 near-perfect audited records per domain** before `tau` can exist, because the binding
   constraint is `threshold_for_risk` at `risk_target=0.02` on a held-out fold. v2's framing
   ("reporting milestone; tau floors `min_calibration_n=200` untouched") points the right way
   but names a bar ~2× too low and is now redundant.

4. **Phase 3 specifies a component that never existed — REFUTED.** v2 twice names an "opt-in
   `FitGuardConfig`". What shipped in the very same PR is
   `CalibrationConfig.min_eval_samples` / `require_discrimination`
   (`agent-core/agent_core/config.py:60-61`) plus keyword-only parameters on
   `evaluate_calibration`. The design changed during implementation and the plan was never
   reconciled, so the plan and the code it shipped beside disagree about what was built.

## Factual drift

5. **Every file:line in the cross-cutting standards table is stale.** The HUMAN_AUDIT filter
   cited as `outcome_store.py:157-199` now sits at **:307**; `test_outcome_store.py:195-198`
   is now **:298**.

6. **"next free today: F-047" — REFUTED.** `features.yaml` now runs to **F-051**; next free is
   F-052. Note **F-040 finally landed**, closing the permanent gap the 07-03 plan created by
   pre-assigning it — the same failure mode as finding 1, now resolved.

7. **Phase 3's premise is largely overtaken, and the companion gap analysis has already been
   maintained without me.** `../../gap-analysis-merge-gate-2026-07-24.md` now carries a
   "Fixed since this report (F-049, ADR 0029, 2026-07-31)" section closing **G1** (
   `GatePolicyConfig` is now both validated via `__post_init__` and CLI-reachable —
   `--risk-target`, `--risk-ci-z`, `--n-bins`, each defaulting off the dataclass), **G2**
   (routing single-sourced in `_bin_of`; bin count in `DEFAULT_N_BINS` +
   `GatePolicyConfig.n_bins`) and **G3** (`_operating_bin_ci_width` returning `None`).
   That re-verification was sharper than the original: it found **G3's stated mechanism
   wrong and its severity understated — reproducing to `AUTO_MERGE` under a stock
   `GatePolicyConfig()`**. It also *widened* **G4** (from 2 CLIs to 4) and correctly
   **refuted G5's headline** while keeping its `record_verdict` sub-claim open. The document
   needs nothing from this review; it is ahead of it.

8. **Phase 4 is no longer hypothetical.** ADR 0026 shipped `agent_core.proxy_eval`, a
   `ProxyExtractor` seam, and PPI++ as a report-only estimator, so "does confidence
   discriminate?" is answerable with a measured ρ — marginal and conditional — rather than
   argued. v2's "K=15 audited agent rows; AUROC bar = min_auroc" is a reasonable criterion
   attached to machinery that did not then exist and now does.

## Claims confirmed accurate

- **Phase 1's shadow-lane defect is still live.**
  `.github/workflows/calibrated-merge-gate.yml:141` still runs
  `merge_gate_context.py "$MECH_FLAG" --output context.json` with neither `--confidence` nor
  `--human`. Eighty-two commits later, untouched.
- **Phase 2 is still the critical path.** Zero `human_audit` records in 83 rows across 46
  change_ids, so `tau is None` in every domain — exactly as v2 said, for exactly the reason
  v2 gave.
- **Phase 3's deliverable is still undone.** No committed calibration report exists under
  `docs/`.
- **The backfill genuinely never ran.** Historical Claude-authored rows remain `human/*`.
- **The "store ground truth / re-measure at every phase start" standard did its job.** It is
  why this drift was caught instead of executed, and it is the one standard in v2 that
  earned its place unambiguously.
- **ADR 0025, landed by the same PR, is now load-bearing.** The `selection_propensity` field
  added by ADR 0026 cites it as why `OutcomeRecord` may be "a deliberately dumb,
  load-tolerant holder". Every line of today's store carries that field; without ADR 0025 an
  older reader would raise on all 83 of them.

## What this says about the plan format

Two of the four execution-breaking findings (1 and 4) are cases where v2 stated something it
could have checked at authoring time. The other two (2 and 3) are honest drift. The v3
rewrite therefore changes one thing structurally: it reserves no identifier and pins no line
number it has not re-derived, and it says so in the standards table with finding 1 as the
citation.

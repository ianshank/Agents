# Peer Review — `docs/gap-analysis-merge-gate-2026-07-24.md` re-verification (2026-07-31)

**Reviewed artifact:** `docs/gap-analysis-merge-gate-2026-07-24.md` §3 (nine open findings) and
§4 (test gaps), written at `961cfd14`; re-verified against `205da23` after PRs #114/#115.
**Method:** four independent sub-agents, full reads of
`agent_core/{merge_gate,merge_gate_ci,outcome_store,calibration,audit_sampler,outcome_labeller}.py`
and their suites, exhaustive grep of every construction and call site, and **independent
reproduction** — every severity claim below was executed, not inferred.
**Outcome:** three findings confirmed, one mechanism refuted, one finding substantially
refuted, three new defects found that the gap analysis never named.

---

## Verdict

The gap analysis is broadly accurate but **understated its own worst finding**. G3 is not a
latent hygiene issue; it reaches `AUTO_MERGE` under stock configuration and is the one health
floor of four that did no work. Two of its supporting claims are wrong in ways that matter to
the fix, and the defect adjacent to it — the wrong measurement axis — is more serious than
either G1 or G2.

## Findings that change execution

**1. G3's stated mechanism is wrong. — REFUTED**
The doc attributes the fail-open to `wilson_interval(0, 0) -> (0.0, 0.0)`. That call is
**unreachable** inside `_upper_half_ci_width`: `if not idx: continue` (`outcome_store.py:189`)
returns before it. The fail-open is the `widest = 0.0` initialiser at `:185` — the identity
element of a `max`-reduction over an empty set. Consequence: hardening `wilson_interval`, the
obvious reading of the doc, would not have fixed G3 at all.

**2. G3 reaches AUTO_MERGE. — CONFIRMED, severity understated**
Reproduced with stock `GatePolicyConfig()`: 6600 HUMAN_AUDIT records with every
`raw_confidence` in `{0.05, 0.45}` yield `CalibratorHealth(n=6600, ece=0.0, auroc=1.0,
bin_ci_width=0.0)`, `is_trustworthy=True`, `tau=1.0`, and `decide(raw_confidence=0.45)` returns
`AUTO_MERGE`. On the fix's regression fixture the same input moves from `0.0` (vacuous pass) to
`0.7935` (honest fail).

**3. The health metric measures the wrong axis. — NEW**
`_upper_half_ci_width` bins by *raw score* halves, but `decide()` gates on the *calibrated* `p`
against `tau` (`merge_gate.py:165-166`). The reproduction auto-merged at raw 0.45 — a region the
function cannot inspect by construction. Its docstring's justification, "the region where
auto-merges actually happen", is false. This is why a sentinel-only fix is insufficient: it
would leave the axis wrong and convert the fail-open into an arbitrary blocker keyed on the
agent's confidence *scale*.

**4. `CalibratorHealth.n` counts both folds. — NEW**
`outcome_store.py:266` used `n=len(recs)` while `ece`/`auroc`/`bin_ci_width` were measured on
`eval_recs` alone. `min_calibration_n=200` was therefore satisfied by ~100 records of evidence
— a 2× overstatement of the floor ADR 0005's sample-size note rests on.

**5. `min_auroc` has no lower guard. — NEW**
`outcome_store.py:261-263` substitutes the sentinel `0.5` for single-class domains and its
comment claims that "fails the health floor". True only while `min_auroc > 0.5`; nothing
enforced it, so `min_auroc=0.5` silently readmitted single-class domains.

## Wrong emphasis / claims that would have propagated

**G2's premise is stale; its conclusion stands.** "…which is what made F1 reachable" — F1 *was*
fixed, but in 1 of 4 implementations, so out-of-range policy became **three-way** inconsistent
rather than two-way: `reliability_bins` raises, `fit` sweeps `>1.0` into the top bin and drops
`<0.0`, `bin_index` floors to bin 0. Because `OutcomeRecord` applies no validation (ADR 0025),
`fit` could build a top-bin accuracy inflated by a score `bin_index` would never route a query
to — a residual the doc does not name.

**G5 is substantially refuted.** "`outcome_labeller` and `audit_sampler` have no logging at
all… `print` only" is **false**: both gained `logger.debug`/`info`/`error` calls since the doc
was written. The live residue is that neither `main()` calls `configure_logging`, which makes
it an instance of **G4**, widening that finding from 2 CLIs to 4. G5's `record_verdict`
non-idempotency sub-claim is confirmed verbatim.

**`agent-core/tests/**` is protected.** `scripts/eval_protected_paths.py:33` — added after the
doc was written. Every PR touching this subsystem's tests needs `eval-change-approved`, which
changes how the work can be split.

**`test_run_bin_conflation_avoided` passes for the wrong reason.** `_fold("lone") == 1`, so the
lone record lands in the held-out fold, makes the domain untrustworthy, and escalates at the
health layer — never reaching the Wilson floor the test exists to exercise.

## Claims confirmed accurate

- **G1** — `GatePolicyConfig` has no `__post_init__` (the only `agent_core` config without one)
  and exactly one bare production construction at `merge_gate_ci.py:148`. It accepts
  `risk_target=1.0`, `min_calibration_n=0`, and NaN. ADR 0005 §3 promises a "human-set
  `risk_target`" with no seam to set it.
- **G2** — the literal `10` is independently re-typed at `outcome_store.py:167`, `:181` and
  `calibration.py:99`, and `build_domain_models` passes none of them; the ECE is computed over a
  binning object independent of the calibrator it measures.
- **§4 test gaps** — the held-out contract is unpinned (identically-distributed folds mean an
  `eval_recs -> fit_recs` mutant passes green); `outcome_labeller`'s precedence is never tested
  with two signals live. Additionally `test_outcome_store.py:134` asserted
  `_upper_half_ci_width([], [], 1.96) == 0.0`, **pinning the defect as correct**.

## Reprioritized recommendations (carried into the proposal)

1. **WS-A — re-axis the width measurement onto the operating region, with `None` for
   unmeasurable.** Subsumes the minimal sentinel fix and closes finding 3. Highest severity.
2. **WS-B — validate `GatePolicyConfig` and expose it.** Prerequisite for WS-A in practice:
   once health is measured honestly, `max_bin_ci_width=0.20` may prove unreachable, and
   retuning it before activation is exactly the human decision ADR 0005 reserves.
3. **WS-C — single-source the bin count and the routing.** Closes G2 and its residual.
4. **WS-D — fold accounting and the mutation-resistant test.** Closes findings 4 and the §4 gaps.
5. **Deferred:** G4 (widened to 4 CLIs), G6, G7, G8, G9 — none can change a gate decision.

## Verification note

Every mutation-resistance claim in WS-D was checked by **applying the mutation and observing
the failure**, not by inspection: `eval_recs -> fit_recs` (3 tests fail, and the pre-existing
healthy-domain test does *not*, confirming it was toothless), `fit_recs -> eval_recs` (1),
`n -> len(recs)` (3), `widest = None -> 0.0` (2), and the labeller branch swap (1).

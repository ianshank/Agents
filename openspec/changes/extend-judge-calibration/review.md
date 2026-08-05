# Review: extend-judge-calibration

**Reviewed:** the externally proposed judge-calibration change against `b52c696`. Full findings:
`docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

The source *plan* was right that this should extend existing mechanisms rather than build a second
calibration system — and right in a way the source *analysis* was not, since that document graded
calibration "Not Covered" outright. But the instruction as written had no legal implementation: the
mechanisms sit on the far side of a structurally enforced airgap.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| B5 | "Extend those mechanisms" across the `eval_harness ⇎ flow_corpus` airgap | Shared probe math goes in `agent_core`, consumed via the existing `agent_core_adapter` edge. No manifest edit, airgap intact |
| B9 | Claimed the golden-set machinery was reusable | Only the hash splitter and held-out discipline are. `GoldenItem` is binary-label with no answer pair; the pairwise corpus is a new type |
| A2/A3/A4 | Source analysis graded κ, human labelling and calibration "Not Covered" | All three refuted against the tree; this change is scoped to what is actually missing — bias probes |

## Assumptions challenged

**Can uncalibrated judges influence a release gate?** Not after this change, and not entirely before
it either — `behavioral_regression` already keeps an unvalidated judge advisory. What is new is that
*bias* joins agreement and power as a gating precondition, so a judge that agrees with humans on
average while systematically preferring the first or longer answer can no longer gate.

**Is agreement sufficient?** No, and this is the change's whole premise. A judge can clear κ against
a human label set and still be order-sensitive, length-biased or self-preferring. Those three are
measurable with controlled transformations and are invisible to agreement alone.

**Is this a second calibration system?** It should not be, and the placement decision is what keeps
it from becoming one. Had the probes been implemented separately inside `eval_harness`, the
repository would have ended with two independent notions of a validated judge — the failure the
source plan correctly warned against but its own instruction would have caused.

**Are canaries necessary?** Yes. A judge that has degenerated to a constant verdict can post a
flattering κ on a skewed corpus. Known-equal, clearly-better and clearly-worse canaries detect a
judge that has stopped discriminating, the same way F-013's discrimination canary does for oracles.

## Residual risk

- **`agent_core` is dependency-free and must stay that way.** Probe math is pure stdlib. Any
  temptation to reach for numpy here would break the zero-dependency invariant that
  `check_charter_invariants.py` enforces.
- **Bias tolerances are policy, not statistics.** Choosing an acceptable order-flip rate is a
  risk-appetite decision like `risk_target` in ADR 0005 §3, and should be set by a human rather than
  defaulted quietly to whatever the first measured judge happens to score.
- **The corpus is the bottleneck.** Order-swapped pairwise calibration needs roughly twice the judge
  calls per item, and the human labels behind it remain the scarce resource — the same constraint
  `audit_capacity_per_cycle` encodes for the merge gate.

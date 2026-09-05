# Review: add-gate-decision-provenance

**Reviewed:** this change did not exist in the source plan. It was extracted during round 1 of the
peer review (`docs/plans/scenario-eval-matrices/REVIEW.md` §A6) and then **substantially rewritten
in round 2**, because round 1's own finding was wrong in its disposition.

## Verdict

The source plan was right that an uncalibrated scorer needs somewhere to run non-blocking, and
wrong that the harness already had it. Round 1 caught that and then proposed the expensive fix
without noticing the cheap one — and without noticing the larger defect sitting next to it.

## Correction to round 1 (2026-09-05, second pass)

Round 1 §A6 said "no report-only gating mode exists" and recommended building
`GateRule.report_only`. The mechanics were right; the disposition was not, in two ways.

**1. Whole-gate non-blocking already ships, at the workflow level.** `evaluate_gate` is a pure
function called from exactly one site (`cli.py:92`) and the exit code is decided in the CLI, so a
CI job can run `eval-harness run` and map its exit code to success — which is exactly what
`calibrated-merge-gate.yml:69-73` does ("all three decision exit codes … map to job success").
Round 1 recommended a protected-path code change over a shipped house pattern without weighing them.

That criticism is accepted but does not fully land, and the proposal now says why: the workflow
pattern is **all-or-nothing**. It disarms every rule including calibrated ones, for the soak's whole
duration, with nothing in the artifact recording that it happened. Per-rule granularity is what
lets a live gate carry an experiment. Both mechanisms are kept, each for the job it fits.

**2. Round 1 missed the bigger finding entirely.** The gate decision is **never persisted**.
`engine.py:411-412` emits to every sink; `cli.py:92` evaluates the gate *afterwards*, uses it for
two `print` calls and an exit code, and discards it. `RunResult` has no gate field and `to_dict()`
emits none (`core/types.py:176-196`).

That is worse than the missing advisory mode and cheaper to fix. It means the `html_file` artifact
the plan proposes to build the VP deliverable from contains no verdict; it means a soak's decisions
live only in CI stdout and cannot be diffed; and it means the claim "these metrics cannot be quietly
weakened" has no artifact demonstrating it. This change is renamed and reordered around that
finding, with advisory rules as the second requirement rather than the first.

## Corrections applied from round 1

| # | Finding | Correction |
|---|---|---|
| A6 (mechanics) | `GateRule` requires a bound; `GateResult` is `passed` + `failures`; no advisory state | Confirmed. `report_only` + `advisory` added |
| A6 (citation) | Plan cited "the repo's existing shadow-mode pattern" as if in the harness | The precedent is real but lives in CI (`calibrated-merge-gate.yml:69-88`, F-035 soak, ADR 0005). Cited correctly, and its limitation stated |
| A6 (disposition) | Round 1 recommended building `report_only` without weighing the workflow alternative | Rewritten; the alternative is named, kept, and bounded |
| — (missed) | Gate decision never reaches any sink | New primary requirement |
| A13 | Plan put thresholds in requirement prose | No numeric literal in this delta |

## Findings raised by this change

**R1 — this needs its own ADR and does not have one.** ADR 0031 authorises additive core-model and
engine changes *for agent evaluation*. A gate field on `RunResult` is additive and is an engine
change, but it is not agent evaluation, so it is outside that grant. Task 0.1 draws the ADR before
implementation. The flywheel proposal's "Do not begin implementation on the strength of it" is the
posture being copied deliberately.

**R2 — the new `engine → gating` edge may be avoidable, and the choice should be measured not
argued.** `architecture.yaml` is protected so that a new component edge gets human review. Injecting
a `gate_evaluator` callable from `from_config` achieves the same result with no new edge. Task 1.3
requires running the drift guard both ways and recording which was taken, rather than settling it
here by assertion.

**R3 — the calibration guard would otherwise make calibration unreachable.**
`require_calibration_for_judge_gating` refuses any configuration whose rules target a judge-backed
scorer without a named artifact. Read literally against a new advisory rule, that blocks the runs
whose output *becomes* the calibration corpus. Scoping the guard to non-advisory rules restores the
intended meaning of "gating" rather than loosening it. Three scenarios, because a reader could
reasonably expect the opposite.

**R4 — `extend-judge-calibration` uses "advisory" for something adjacent.** Its requirement reads
"A judge SHALL remain advisory unless its held-out human agreement, statistical power, and
configured bias tolerances all pass." Implemented through the existing guard, "advisory" there means
*the configuration is refused* — fail-closed, correct, unchanged here. This change adds the third
state that phrasing implies but the harness cannot express: a rule that runs, reaches a verdict, and
records it without blocking. Complementary, not superseding.

Flagged for that change's owner rather than acted on; this change does not edit another change's
in-flight delta.

## Open questions for the reviewer

1. Should the persisted decision carry per-item detail, or only the aggregate verdict? Aggregate
   only here — per-item gate attribution is a larger design and the aggregate is what a soak diffs.
2. Should `advisory` entries carry `attempt_index` when `repetitions > 1`? Left out; the aggregate
   is already per-item. Cheap to add later, not cheap to remove.

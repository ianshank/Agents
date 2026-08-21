# 0035 — PanelJudge: aggregate N member judges, abstain rather than guess (F-059)

- Status: **Accepted.** Additive on top of the judges registry; off unless a config's `judge.type`
  is `panel`.
- Date: 2026-08-21
- Related: F-059, `extend-judge-calibration` (F-057, the calibration-artifact gating this panel's
  members inherit unchanged), `src/eval_harness/judges/panel.py`,
  `src/eval_harness/agent_core_adapter/{__init__.py,calibration.py}`,
  `agent_core.judge_calibration_report`.

## Context

A single LLM judge is a single point of *systematic* failure: order bias, verbosity preference,
self-preference are exactly the three probes `extend-judge-calibration` (F-057) exists to catch,
and catching them doesn't fix them — an individual judge stays exposed to whichever bias its own
calibration run didn't happen to probe. Running several independent judges and aggregating their
verdicts is the standard mitigation, but it raises three design questions this ADR settles:

1. **What does the harness do when members disagree?** Averaging disagreement into one confident-
   looking score would be the worst outcome — it hides exactly the signal a panel exists to
   surface.
2. **Does a panel change how much it costs to run?** `BudgetedJudge` (F-022/F-030) was written
   assuming one provider call per `evaluate()`. An N-member panel breaks that assumption silently
   unless the wrapper is taught about it.
3. **Does a panel need its own calibration story**, or does it inherit the single-judge one
   unchanged?

## Decision

1. **`PanelJudge`, registered `panel`** (`src/eval_harness/judges/panel.py`). Members are built
   once at construction, via the same `JUDGES` registry the engine itself uses (mirrors
   `CompositeScorer`'s registry-built-children pattern), and evaluated *sequentially* in
   declaration order — required for the determinism guarantee a thread-pooled fan-out could not
   give. Three aggregation strategies: `median` (default), `mean`, `majority` (a pass *fraction*
   at `member_pass_threshold`, not a score in the members' own space).
2. **Abstention, not averaging, on disagreement.** Two independent triggers, checked in order:
   - **Quorum.** A member whose call raises is excluded from aggregation — never silently
     recorded as a `0.0` vote. If fewer than `quorum` members survive (default a simple majority,
     `len(members)//2 + 1`), the panel abstains.
   - **Disagreement threshold.** If the spread between the highest and lowest surviving score
     exceeds an optional `disagreement_threshold`, the panel abstains even with full quorum.

   An abstained verdict carries `raw["abstained"] = True` and a configurable `on_skip` score
   (default `0.0`). This mirrors the house convention everywhere else an uncertain verdict is
   surfaced rather than guessed: `Decision.CANT_TELL` in campaigns, `cant_tell` in the regression
   estimate, `OracleResult.verdict = None` routing to a human audit queue.

   **Downstream propagation is duck-typed, not panel-specific**: `LLMJudgeScorer.score` reads
   `verdict.raw.get("abstained") is True` and reports `ScoreResult.passed = None` in that case —
   the same `passed=None` "this evaluator declined to score" contract `AutoevalsScorer` already
   established for its own skip case. Any judge that sets this flag gets the same treatment; the
   scorer has no import of, or special case for, `PanelJudge`.
3. **`calls_per_evaluate` fixes the budget/rate-limit under-charge.** `PanelJudge.calls_per_evaluate`
   is `sum(getattr(member, "calls_per_evaluate", 1) for member in members)` — public, duck-typed,
   *recursive* (a nested panel-of-panels correctly reports its true call count, not its top-level
   member count). `BudgetedJudge` reads the same attribute off whatever it wraps (default `1`, so
   every existing single-call judge is unaffected byte-for-byte) and scales both the cost
   reservation and the rate-limiter's slot consumption by it. `_SlidingWindowLimiter` gained atomic
   `try_acquire_n`/`acquire_blocking_n` (replacing the old single-slot methods) to make an N-slot
   reservation genuinely atomic — check-then-reserve-all-or-none, since there is no "release" to
   unwind a partial one. `build_budgeted_judge` fails fast at construction if a panel's
   `calls_per_evaluate` exceeds `max_per_window` — no amount of waiting grows the window, so
   deferring the error to the first blocked call would just deadlock.
4. **Calibration extends additively, not separately.** `agent_core.JudgeCalibrationReport` gains
   three trailing, defaulted fields — `pairwise_member_kappa`, `abstention_rate`,
   `member_families` — informational only, never read by `may_gate`/`failing_checks`. A panel's
   report gates through the *exact same* `require_report_to_gate` a single judge's does; a test
   proves this by holding every gating-relevant value identical between a mock-shaped and a
   panel-shaped report and asserting byte-identical outcomes. `pairwise_member_kappa()`
   (`agent_core_adapter/calibration.py`, split out to stay under the file-size budget) computes
   Cohen's kappa between every pair of members' binarized pass/fail decisions across a corpus,
   reusing `agent_core.golden.cohen_kappa` rather than re-deriving it.
5. **No new `architecture.yaml` edge.** `panel` is a registered `Judge`, reached through the
   already-declared `eval_harness.judges` component the same way every other judge is;
   `calibration.py` is a new file inside the already-declared
   `agent_core_adapter: [agent_core, config, core]` edge, not a new dependency.

### Example configuration

```yaml
judge:
  type: panel
  params:
    strategy: median              # median (default) | mean | majority
    quorum: 2                     # default: len(members)//2 + 1
    disagreement_threshold: 0.3   # optional; omit to never abstain on spread alone
    on_skip: 0.0                  # score recorded on an abstained verdict
    members:
      - name: gpt_reviewer
        type: openai
        params: { model: gpt-4.1, score_field: score }
      - name: claude_reviewer
        type: anthropic
        params: { model: claude-opus-4-8, score_field: score }
      - type: mock                # a third, offline member for deterministic CI runs
        params: { default_score: 0.8 }
```

## Consequences

- **Positive.** A panel's disagreement is a first-class, queryable signal (`raw["spread"]`,
  `raw["stdev"]`, `abstained`), not silently averaged away — and a caller gets `passed=None`
  automatically, with no panel-aware code of its own.
- **Positive.** The N-call budget/rate-limit bug this ADR fixes (`BudgetedJudge` reserving 1 unit
  for what could be an N-provider-call evaluation) generalizes beyond panels: any future judge
  that internally fans out to more than one provider call inherits the same correct accounting for
  free, by declaring `calls_per_evaluate`.
- **Negative.** A panel is strictly more expensive than a single judge (N provider calls per item,
  by design) — `calls_per_evaluate`'s whole purpose is making that cost visible to the budget
  system, not hiding it.
- **Neutral.** No behaviour changes for any existing single-judge configuration:
  `calls_per_evaluate` defaults to `1` everywhere it's read, and the three new
  `JudgeCalibrationReport` fields default to empty/`None`.

## Compliance

Enforced by tests, not review alone: `tests/test_panel_judge.py` and
`tests/test_matrix_panel_judge.py` (judge floor M1/M2/M3/M6, plus M5 voluntarily — panel's
aggregation/quorum/abstention logic is repo-owned, unlike the "verdict determinism is the
provider's" exclusion the floor otherwise grants judges); `tests/test_budgeted_judge.py`
(cost/rate scaling, the construction-time window guard, and `_SlidingWindowLimiter`'s atomic
N-slot acquisition directly); `agent-core/tests/test_judge_calibration_report.py` and
`tests/test_agent_core_adapter.py::TestPanelVsMockGatingParity` (calibration fields, gating
parity); `tests/test_plugin_registry_surface.py` and `tests/test_public_surface.py` (frozen
baselines); `scripts/extract_registries.py --check` (README currency).

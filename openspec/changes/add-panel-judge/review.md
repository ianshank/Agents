# Review: add-panel-judge

**Reviewed:** this package's own draft against `1314e12`, in two passes — a mechanical
fact-check of every falsifiable claim (verdicts CONFIRMED / CORRECTED / REFUTED) and an
adversarial design review with attacks verified before kept. Refuted attacks are recorded,
not deleted. House precedent: `docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

The panel is genuinely new surface — an exhaustive grep for
panel/consensus/quorum/committee/council/arbiter across the tree hits only the
`CompositeScorer` `ensemble` alias, F-020 and their tests — and it lands cleanly through the
registry with no engine, core-model, or manifest change. The draft survived review with four
corrections, two of which (the budget under-charge and the `JudgeVerdict` shape) would have
shipped real defects had they reached implementation unexamined.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| C1 | A naive panel under-charges `judge_budget` and the F-030 rate window by factor N — `BudgetedJudge` reserves once per `evaluate()` (`agent_core_adapter/__init__.py:326`) | Duck-typed `calls_per_evaluate` read in `build_budgeted_judge` (absent → 1); the panel exposes `len(members)`. Promoted to its own spec requirement with the under-charge regression scenario |
| C2 | The draft placed per-member detail in a `metadata` field — `JudgeVerdict` has none; it is `score / reasoning / raw` only (`core/types.py:134-140`); `ScoreResult` is the dataclass with `metadata` | All panel evidence lives in `raw`; the core model is not extended |
| C3 | The draft assumed panel breakdowns reach results — `LLMJudgeScorer` drops `verdict.raw` before building `ScoreResult` (`scorers/__init__.py:208-218`) | Scoped out as an explicit non-goal and named follow-up surface, rather than a silent promise the current seam cannot keep |
| C4 | A `council` alias for discoverability | Dropped. `FROZEN_ALIAS_MAP["judge"]` is asserted by exact equality (`tests/_matrix_coverage.py`), so an alias is a deliberate frozen-map edit, and this one earns nothing |

## Attacks that died under verification (kept per house style)

**"This is just `CompositeScorer` at the judge seam — extend it instead."** Refuted twice
over. `CompositeScorer` aggregates `ScoreResult`s and runs at the scorer seam, which the
budget guard does not wrap — `AutoevalsScorer` documents that boundary
(`scorers/__init__.py:242-245`) — so a panel built there escapes `judge_budget` and the rate
limiter entirely. And its weighted-mean contract is the wrong shape: a weighted panel is a
panel whose disagreement can be tuned away.

**"Fan-out needs `agent_core`'s `ParallelClaimRunner` or a new orchestration layer."**
Refuted. N in-process member calls inside one `evaluate()` need no runner; the engine's
existing parallelism (`engine.py`, per-item RNG, `BudgetedJudge` lock) is untouched. The
moment the panel needs a loop controller it has become an executor, which the fleet contract
forbids (`openspec/AGENTS.md`, "the subject vs the executors").

## Assumptions challenged

**Do N members buy N× trust?** No, and the design says so mechanically. Members sharing a
model family — or a training distribution — fail together; consensus among correlated judges
is one opinion with extra invoices. Hence pairwise member–member κ in the calibration
artifact: redundancy is measured, not assumed away. The panel's honest value is the
*disagreement* signal, not vote-count confidence.

**Is abstention a cop-out?** It is the house position. `CANT_TELL` in campaigns, `cant_tell`
in the regression estimate, `OracleResult.verdict = None` to the audit queue — every
measuring subsystem in this repo prefers "no claim" to a fabricated number. A panel that
averages a 0.1 and a 0.9 into a confident 0.5 is strictly worse than either member alone.
The counterweight is also specified: abstention rate is reported in the calibration
artifact, so a panel that abstains its way out of usefulness is visible.

**Why is `median` the default and not `mean`?** One deranged member — a provider outage
mid-response, a parse failure scored fail-safe 0.0 — moves a three-member mean by a third of
its error and the median not at all. The mean remains available, chosen explicitly.

**Can the offline suite actually validate this?** The mechanics, yes: determinism,
aggregation, abstention, quorum, budget accounting all run on `MockJudge` members
(`judges/__init__.py:21-39`). What it cannot produce is *real* inter-provider disagreement —
that only exists live, which is exactly why the calibration obligations are part of the
proposal rather than an afterthought.

## Residual risk

- **Cost is N× by construction.** The budget guard now states it honestly, but an operator
  who swaps `mock` members for three provider judges multiplies spend per item by three.
  The config example must say so out loud.
- **The disagreement threshold is policy, not statistics.** Like the bias tolerances in
  `extend-judge-calibration` and `risk_target` in ADR 0005, an acceptable spread is a
  risk-appetite decision — it should be set by a human, not defaulted to whatever the first
  measured panel happens to produce. The default (`None` = never abstain) is deliberately
  the least surprising, not the most protective.
- **Diversity is necessary, not sufficient.** Declaring distinct model families bounds the
  most obvious correlation; it does not remove shared-training-data correlation between
  providers. The pairwise-κ report measures what declaration cannot.
- **`majority` inherits its binarisation.** The strategy is only as meaningful as
  `member_pass_threshold`; two panels with the same members and different thresholds are
  different instruments. The threshold is a documented config field for exactly this reason.

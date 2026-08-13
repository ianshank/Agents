# Review: add-panel-judge

**Reviewed:** this package's own draft against `1314e12`, in two passes — a mechanical
fact-check of every falsifiable claim (verdicts CONFIRMED / CORRECTED / REFUTED) and an
adversarial design review with attacks verified before kept. Refuted attacks are recorded,
not deleted. House precedent: `docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

The panel is genuinely new surface — `grep -riE
'panel|consensus|quorum|committee|council|arbiter'` over `src/` and `tests/` Python returns
nothing, and `ensemble` appears only as an alias of the `weighted` **scorer**
(`scorers/__init__.py:108`), never at the judge seam. The grep is scoped to implementation
code on purpose: these proposal documents introduce the vocabulary, so an unscoped claim
would falsify itself the moment the package landed. The change lands cleanly through the
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

## Second pass (2026-08-13) — the proposal leaked the very signal it was written to protect

A second adversarial pass, run against `2c0b077` after the package was first pushed, re-derived
every falsifiable claim in these documents rather than trusting the first pass. **The finding
that matters is structural:** this change exists because signal was being destroyed at a
boundary (the budget under-charge at the `BudgetedJudge` wrapper, C1). The first draft then
committed the identical error at two further boundaries it never examined, and understated a
third. Each is corrected below; the design and spec deltas were rewritten under them.

| # | Severity | Finding | Correction |
|---|---|---|---|
| C5 | **critical** | **Abstention is destroyed at the scorer boundary.** `design.md` claimed abstention "mirrors `CANT_TELL` / `cant_tell` / `OracleResult.verdict = None`". It does not: `LLMJudgeScorer.score` sets `passed=verdict.score >= self.threshold` (`scorers/__init__.py:214-217`) with no `None` path, so an abstention scored `abstain_score=0.0` arrives downstream as `passed=False` — a *confident negative*, the exact failure mode this change exists to prevent | Abstention reaching results as "no verdict" is now a **required** requirement, not the deferred follow-up C3 called it. `LLMJudgeScorer` gains an abstention-aware path (`[P]`) |
| C6 | major | **`calls_per_evaluate = len(members)` recreates C1 one level up.** A member that is itself a `panel` performs N calls, not one, so the fix for the factor-N under-charge under-charges nested panels by the same mechanism. Nesting is legal by construction: members are built by `JUDGES.create`, and `panel` is registered in `JUDGES` | `sum(getattr(m, "calls_per_evaluate", 1) for m in members)` — the same duck-typed read, applied one level down |
| C7 | major | **The determinism scenario is unimplementable as written.** "both verdicts are identical, including the raw payload" requires a deterministic member call order, which no document stated. A `ThreadPoolExecutor` implementation would satisfy every other requirement and fail this one intermittently | Member evaluation is specified sequential in declaration order. Precedent for the parallel alternative, if ever needed: `EvalEngine._run_parallel` reassembles by submission order |
| C8 | major | **"Reuses `cohen_kappa` unchanged" was overstated.** `agent-core/agent_core/golden.py:144` is `cohen_kappa(r1: Sequence[int], r2: Sequence[int]) -> float` — **integer** labels, exactly **two** raters. Pairwise member redundancy over N members needs N(N-1)/2 invocations plus a float→label discretisation step that does not exist in the tree | The obligation now names the discretisation and the pair count as work, not as reuse |
| C9 | minor | **`BudgetedJudge.attach_client` was cited as working precedent; it is dead code on the engine path.** `engine.py:113-117` attaches the client to `[dataset, judge, *sinks]`, then `engine.py:127` *replaces* `judge` with the `BudgetedJudge` wrapper — so the wrapper's delegating `attach_client` is never invoked by the engine | Citation corrected. The panel's own fan-out is unaffected and necessary: the panel *is* the top-level `judge` at line 115, so it receives the call its members never would. Pre-existing tree defect, recorded below, not fixed here |

### Edge cases the first draft did not specify

Each was executed against the stdlib rather than reasoned about, since `statistics` is what an
implementer will reach for (`engine.py:12` already imports it; `fmean` at `:214`):

- **`median` of an even-sized panel is the mean of the middle two** — `statistics.median([0.2, 1.0])
  == 0.6`. At N=2 the default strategy *is* `mean`, which erases the outlier-robustness that
  justified making `median` the default. Specified explicitly, with `median_low` named as the
  alternative that preserves it.
- **A one-member panel is legal and degenerate** — `pstdev([0.9]) == 0.0`, so spread is always
  0, `disagreement_threshold` is inert, and the panel is a judge with extra cost. Now rejected
  at construction.
- **`majority` returns a value in a different space than `median`/`mean`** — a pass *fraction*,
  not a score in the members' score space, yet both are compared against the same
  `LLMJudgeScorer.threshold`. Three members each scoring 0.6 yield `median=0.6` but
  `majority=1.0`. Documented per strategy rather than left to be discovered.
- **The quorum denominator was ambiguous** (configured members vs survivors). Fixed to
  configured members; a survivor-relative quorum is trivially self-satisfying.

### Matrix obligation, corrected

`REQUIRED_DIMS["judge"]` is `{1, 2, 3, 6}` and excludes M5 with the comment *"verdict
determinism is the provider's"* (`tests/_matrix_coverage.py:66-73`). That rationale **does not
hold for a panel**: its aggregation, abstention and quorum logic are deterministic repo-owned
code, not a provider's sampler. The panel therefore carries M5 rows voluntarily, above its
floor — the "subset-meaningful dims are extra rows, welcome, never required" case the policy
comment anticipates.

### Attacks that died under verification (second pass, kept per house style)

**"`passed=None` is a new concept the results model can't carry."** Refuted twice.
`ScoreResult.passed` is `bool | None` (`core/types.py:129`); `AutoevalsScorer` already emits
`value=self.on_skip, passed=None, comment="autoevals skipped (score=None)"`
(`scorers/__init__.py:307-313`); and `EvalEngine._aggregate` already excludes `None` from
`pass_rate` and returns `None` when every verdict is `None` (`engine.py:210-211`). The entire
downstream stack is built for abstention. `LLMJudgeScorer` is the sole reason it cannot arrive
— which is what makes C5 a small fix rather than a redesign, and what made shipping it as a
"non-goal" a mistake.

**"Name the config field `abstain_score`."** Refuted. `AutoevalsScorer.on_skip` is the
established name for "the value recorded when this evaluator declined to score", in the same
module. A second name for one concept is how two vocabularies start.

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

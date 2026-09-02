# Design: add-panel-judge

## Placement

| Concern | Home | Why |
|---|---|---|
| `PanelJudge` component | `src/eval_harness/judges/` | It *is* a judge: satisfies the `Judge` Protocol (`core/interfaces.py:66-70`), registered `@JUDGES.register("panel")`, resolved by name like every other member of the registry |
| Per-member budget accounting | `src/eval_harness/agent_core_adapter/` | `build_budgeted_judge` already owns the reservation logic; a duck-typed `calls_per_evaluate` read keeps the change additive and the wrapper outermost |
| κ math for calibration obligations | `agent-core/agent_core/golden.py` (existing `cohen_kappa`) | Dependency-free, importable from both sides of the airgap, already shipped — nothing new is written |
| Panel calibration reporting | the `JudgeCalibrationReport` proposed by `extend-judge-calibration` | One calibration system; the panel adds fields (pairwise member κ, abstention rate), not a parallel report type |

No new component edge is declared and `architecture.yaml` is not edited. The engine, core
models, and registries are unmodified; the panel arrives purely through registration, so
CHARTER §4 invariant 1 is satisfied without the ADR 0031 exception.

## Aggregation and abstention

Members come from config as `members: list[dict]` of `{type, params?, name?}` specs, built
once at construction via `JUDGES.create(type, params)` — the same registry the engine uses,
mirroring `CompositeScorer` (`scorers/__init__.py:148`). Validation raises on an empty member
list, a non-mapping spec, or a missing `type`; strategies are an enumerated tuple
(`_STRATEGIES = ("median", "mean", "majority")`, default `median`) and an unknown strategy
raises `ValueError`, mirroring `CompositeScorer`'s single-strategy precedent.

- `median` (default) — robust to a single outlier member; one deranged verdict cannot move
  the aggregate the way it moves a mean.
- `mean` — the plain average, for operators who want it; never a silent default.
- `majority` — binarises each member score at `member_pass_threshold` (a config field
  defaulting to `0.5`, the same default `LLMJudgeScorer.threshold` uses) and returns the
  passing fraction.

Every aggregate carries its evidence: `JudgeVerdict.raw` records the per-member breakdown
(`{name, score, reasoning}`), the spread (max − min), the population standard deviation, the
strategy, and the abstention flag. `raw` is the only home available — `JudgeVerdict` is
`score / reasoning / raw` with no metadata field (`core/types.py:134-140`) — and the core
model is deliberately not extended.

**Abstention is the point — and it must survive the scorer boundary.** With
`disagreement_threshold` set (default `None` = never abstain) and spread above it, the panel
returns the configured `on_skip` value, a reasoning string naming the spread and threshold,
and `raw["abstained"] = True`. The field is named `on_skip` because that is already this
package's name for "the value recorded when this evaluator declined to score"
(`AutoevalsScorer.on_skip`, `scorers/__init__.py:307-313`); a second name for one concept is
how two vocabularies start. A disagreeing panel that averages anyway is strictly worse than
a single judge: it launders uncertainty into false precision.

The claim that this "mirrors `CANT_TELL` / `cant_tell` / `OracleResult.verdict = None`" is
only true once one more thing changes, and the first draft of this design was wrong to
assume otherwise (review C5). `LLMJudgeScorer.score` sets
`passed=verdict.score >= self.threshold` (`scorers/__init__.py:214-217`) with no `None`
path, so an abstention scored `0.0` arrives as `passed=False` — a confident negative, which
is the failure this whole component exists to prevent.

The rest of the stack is already built for abstention, which is what makes this a small fix
rather than a redesign:

- `ScoreResult.passed` is `bool | None` (`core/types.py:129`).
- `AutoevalsScorer` already emits `value=self.on_skip, passed=None, comment=...` when its
  evaluator declines (`scorers/__init__.py:307-313`).
- `EvalEngine._aggregate` already excludes `None` from `pass_rate` and returns `None` when
  every verdict is `None` (`engine.py:210-211`).
- `CompositeScorer` already ignores `None` child verdicts rather than treating them as
  failures (`scorers/__init__.py:172-175`).

`LLMJudgeScorer` is therefore the sole reason an abstention cannot reach results, and giving
it an abstention-aware path is a required part of this change — a protected-path edit
(`src/eval_harness/scorers/**`), not the follow-up the first draft called it.

## Member failure and quorum

A member that raises is excluded from aggregation and recorded in
`raw["failed_members"]` with its exception text — exclusion, not a fabricated `0.0` vote,
for the same reason `kappa_gate` excludes indeterminate pairs instead of inventing a third
category. If fewer than `quorum` members survive (a config field defaulting to a simple
majority of the configured members), the panel abstains with a reasoning string naming the
survivor count. A panel outage therefore degrades exactly like a single-judge outage — a
fail-safe verdict, never a crashed run — while remaining distinguishable in `raw`.

## Edge cases and degenerate configurations

Each was executed against the stdlib rather than reasoned about, because `statistics` is what
an implementer reaches for and is already this package's aggregation dependency
(`engine.py:12`, `fmean` at `:214`). Reuse it; do not hand-roll a median.

| Case | Observed behaviour | Decision |
|---|---|---|
| `median` with even N | `statistics.median([0.2, 1.0]) == 0.6` — the mean of the middle two | Documented, not silently inherited. At N=2 the default strategy *is* `mean`, erasing the outlier-robustness that justified the default. `statistics.median_low` is named as the alternative that preserves it |
| One-member panel | `pstdev([0.9]) == 0.0`; spread is always 0, `disagreement_threshold` is inert | Rejected at construction — a one-member panel is a judge with extra cost and a disabled safety mechanism |
| `majority` output space | Three members each scoring 0.6 give `median == 0.6` but `majority == 1.0` | `majority` returns a pass *fraction*, not a score in the members' space, yet both are compared against one `LLMJudgeScorer.threshold`. Documented per strategy |
| Quorum denominator | "simple majority" was ambiguous between configured and surviving members | Fixed to **configured** members; a survivor-relative quorum is trivially self-satisfying |
| Member call order | Required for the determinism guarantee, previously unstated | Sequential, in declaration order. If parallelism is ever wanted, `EvalEngine._run_parallel`'s submission-order reassembly is the precedent to copy |

## Budget and rate accounting

`BudgetedJudge.evaluate` reserves once per call (`agent_core_adapter/__init__.py:326`), so a
naive N-member panel under-charges the budget and the F-030 rate window by a factor of N.
`build_budgeted_judge` gains one additive behaviour: read `getattr(inner,
"calls_per_evaluate", 1)` and reserve `cost_per_call × calls_per_evaluate` (and that many
rate-limit slots) per evaluation. Every existing judge lacks the attribute and keeps factor
1; no signature changes, no config migration.

The panel's own value **must be computed, not counted** (review C6). `len(members)` is wrong
the moment a member is itself a panel — legal by construction, since members are built by
`JUDGES.create` and `panel` is registered in `JUDGES` — because that member performs its own
N calls, not one. Counting members instead of calls would recreate the exact under-charge
this section exists to fix, one level up. The correct value is therefore recursive, using the
same duck-typed read:

```
calls_per_evaluate = sum(getattr(m, "calls_per_evaluate", 1) for m in members)
```

Two consequences worth stating plainly:

- Panels are N× the cost of a single judge per item. That is the price of a disagreement
  signal, and the budget guard now states it honestly instead of hiding it.
- The panel must sit at the `Judge` seam to be governed at all. `AutoevalsScorer` documents
  the boundary (`scorers/__init__.py:242-245`): provider calls outside `ctx.judge` run
  outside `judge_budget` and the rate limiter. A "panel scorer" would have escaped both.

## Tracing

`attach_client` is a duck-typed, optional hook — not on the `Judge` Protocol — that the
engine calls on `[dataset, judge, *sinks]` when a component exposes it
(`engine.py:113-117`). The panel forwards it to every member; without that fan-out, Langfuse
tracing silently dies for members while the panel itself appears traced.

The first draft cited `BudgetedJudge.attach_client` (`agent_core_adapter/__init__.py:334-338`)
as the precedent for this delegation. That citation was wrong and is withdrawn (review C9):
the engine attaches the client at `engine.py:113-117` and only *then* replaces `judge` with
the `BudgetedJudge` wrapper at `engine.py:127`, so the wrapper's delegating `attach_client`
is never invoked on the engine path. The panel is unaffected — it *is* the top-level `judge`
object at line 115, so it receives the call its members never would — but the delegation it
imitates is dead code, and that is a pre-existing defect of the tree rather than a pattern to
follow. Recorded in `review.md`; not fixed by this change.

## What is reused, and what is not

**Reused:** the registry-built-children pattern and enumerated-strategies precedent from
`CompositeScorer` (`scorers/__init__.py:108-155`); the fail-safe verdict convention from the
provider judges and `BudgetedJudge.skip_score`; `agent_core.golden.cohen_kappa`
(`golden.py:144`) for both panel-versus-human and member-versus-member agreement;
`MockJudge` (`judges/__init__.py:21-39`) as the deterministic member for the entire offline
suite; the `ComponentSpec {type, params}` config shape (`config/models.py:17-21`) —
`params` flows to the constructor via `Registry.create` (`core/registry.py:49-50`), so
member validation lives in the constructor like every other component.

**Not reused:** `CompositeScorer` itself. It aggregates `ScoreResult`s under weights at the
scorer seam; the panel aggregates `JudgeVerdict`s at the judge seam, where the budget guard
lives and where `LLMJudgeScorer` and the `agent_core_adapter` loop already consume verdicts.
Weights are also deliberately absent from the panel: a weighted panel is a panel whose
disagreement can be tuned away, which defeats the instrument.

## Logging

Following the house convention (`AGENTS.md` "Logging"; precedent in
`src/eval_harness/judges/__init__.py`): a module-level `logger =
logging.getLogger(__name__)`, no `logging.basicConfig` in library code. `PanelJudge` logs:

- `logger.debug` per member call — member name and the type it resolved to, matching
  `OpenAIJudge`'s `logger.debug("Calling OpenAI API: ...")` (`judges/__init__.py:150`).
- `logger.warning` on a member exception, mirroring the existing
  `logger.warning("Returning default failure verdict due to parsing error: %s", exc)`
  pattern (`judges/__init__.py:191`, `:291`) — a member failure is handled, not silent.
- `logger.warning` on abstention (disagreement-threshold or below-quorum), once per
  `evaluate()` call, naming the spread/survivor count already carried in `raw` — so an
  operator scanning logs sees a panel losing confidence without opening the run artifact.
- `logger.info` is reserved for once-per-run summaries, per the house convention; a panel
  has no natural once-per-run event of its own (`evaluate()` is per-item), so this level is
  not used by the component itself.

No new logging seam is introduced; this is the same `logging` module every other component
in the package uses, tested the same way (`pytest -o log_cli=true --log-cli-level=DEBUG`).

## Calibration obligations

A panel is a judge and inherits a judge's burden of proof. Aligned with
`extend-judge-calibration`, not competing with it:

- **Panel-level κ.** The aggregated verdict is validated against human labels with
  `cohen_kappa` under the same held-out and power discipline as any single judge.
- **Member redundancy.** Pairwise member–member κ is computed and reported. High
  inter-member agreement means correlated errors and an effective panel size near one — N
  API bills for one opinion. The report states it; policy decides what to do about it.
  **This is work, not reuse** (review C8): `cohen_kappa` is
  `(r1: Sequence[int], r2: Sequence[int]) -> float`
  (`agent-core/agent_core/golden.py:144`) — *integer* labels, exactly *two* raters. Panel
  redundancy over N members needs N(N-1)/2 invocations plus a float-score→label
  discretisation step that does not exist in the tree. The function is reused unchanged; the
  discretisation rule and the pairing loop are new and must be specified, not assumed.
- **Diversity is config, reported.** Member model families are declared and carried into
  the calibration artifact, so "three members, one family" is visible rather than implied.
- **Abstention rate is reported.** A panel that abstains constantly is not measuring; the
  rate belongs in the calibration artifact alongside κ.
- **Advisory unless authorised.** The panel gates nothing unless a gating configuration
  names the calibration artifact ID that authorised it — the `extend-judge-calibration`
  rule, applied unchanged to the aggregate.

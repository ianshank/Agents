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

**Abstention is the point.** With `disagreement_threshold` set (default `None` = never
abstain) and spread above it, the panel returns the configured `abstain_score` (default
`0.0` — the same fail-safe the OpenAI/Anthropic/Phoenix judges return for an unparseable
response and `BudgetedJudge.skip_score` returns on exhaustion), a reasoning string naming
the spread and threshold, and `raw["abstained"] = True`. A disagreeing panel that averages
anyway is strictly worse than a single judge: it launders uncertainty into false precision.
The abstention mirrors `CANT_TELL` / `cant_tell` / `OracleResult.verdict = None` — the house
answer to "the measurement stopped working" is to say so.

## Member failure and quorum

A member that raises is excluded from aggregation and recorded in
`raw["failed_members"]` with its exception text — exclusion, not a fabricated `0.0` vote,
for the same reason `kappa_gate` excludes indeterminate pairs instead of inventing a third
category. If fewer than `quorum` members survive (a config field defaulting to a simple
majority of the configured members), the panel abstains with a reasoning string naming the
survivor count. A panel outage therefore degrades exactly like a single-judge outage — a
fail-safe verdict, never a crashed run — while remaining distinguishable in `raw`.

## Budget and rate accounting

`BudgetedJudge.evaluate` reserves once per call (`agent_core_adapter/__init__.py:326`), so a
naive N-member panel under-charges the budget and the F-030 rate window by a factor of N.
`build_budgeted_judge` gains one additive behaviour: read `getattr(inner,
"calls_per_evaluate", 1)` and reserve `cost_per_call × calls_per_evaluate` (and N rate-limit
slots) per evaluation. `PanelJudge` exposes `calls_per_evaluate = len(members)`. Every
existing judge lacks the attribute and keeps factor 1; no signature changes, no config
migration.

Two consequences worth stating plainly:

- Panels are N× the cost of a single judge per item. That is the price of a disagreement
  signal, and the budget guard now states it honestly instead of hiding it.
- The panel must sit at the `Judge` seam to be governed at all. `AutoevalsScorer` documents
  the boundary (`scorers/__init__.py:242-245`): provider calls outside `ctx.judge` run
  outside `judge_budget` and the rate limiter. A "panel scorer" would have escaped both.

## Tracing

`attach_client` is a duck-typed, optional hook — not on the `Judge` Protocol — that the
engine calls when a component exposes it. The panel forwards it to every member, exactly as
`BudgetedJudge` forwards to its inner judge (`agent_core_adapter/__init__.py:334-338`);
without the fan-out, Langfuse tracing silently dies for members while the panel itself
appears traced.

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

## Calibration obligations

A panel is a judge and inherits a judge's burden of proof. Aligned with
`extend-judge-calibration`, not competing with it:

- **Panel-level κ.** The aggregated verdict is validated against human labels with
  `cohen_kappa` under the same held-out and power discipline as any single judge.
- **Member redundancy.** Pairwise member–member κ is computed and reported. High
  inter-member agreement means correlated errors and an effective panel size near one — N
  API bills for one opinion. The report states it; policy decides what to do about it.
- **Diversity is config, reported.** Member model families are declared and carried into
  the calibration artifact, so "three members, one family" is visible rather than implied.
- **Abstention rate is reported.** A panel that abstains constantly is not measuring; the
  rate belongs in the calibration artifact alongside κ.
- **Advisory unless authorised.** The panel gates nothing unless a gating configuration
  names the calibration artifact ID that authorised it — the `extend-judge-calibration`
  rule, applied unchanged to the aggregate.

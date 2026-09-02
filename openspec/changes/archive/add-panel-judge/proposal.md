# Change: add-panel-judge

**Status:** implemented (archived; landed `955bc9c`) · **Date:** 2026-08-13 · **Author track:** `claude/` agent lane
**Motivated by:** a council-of-agents review of how the harness's own eval tools are
validated — and the grep-verified fact that no panel/consensus/quorum concept exists in the
implementation (`grep -riE 'panel|consensus|quorum|committee|council|arbiter'` over `src/`
and `tests/` Python returns nothing; scoped to implementation deliberately, since these
proposal documents introduce the vocabulary themselves).
**Compiles down to:** a `docs/plans/` PLAN + F-IDs (claimed at land) + a design ADR.

## Why

Every evaluation run carries exactly one judge: `EvalEngine.__init__` takes
`judge: Judge | None` (`src/eval_harness/engine.py:66`) and `RunContext.judge` is a single
object (`src/eval_harness/core/types.py:234-247`). The only "combine N evaluators" component
is `CompositeScorer` (`src/eval_harness/scorers/__init__.py:108`), which combines *scorers*,
not judges, and supports a single strategy (`weighted_mean`).

A single LLM judge is a single point of *systematic* failure. The sibling change
`extend-judge-calibration` documents the failure modes — order bias, verbosity preference,
self-preference — that agreement metrics alone cannot see. A panel of member judges makes a
complementary signal measurable per item: **disagreement**. When independent members score
the same output far apart, that spread is evidence about the judging machinery itself — the
prompt, the rubric, or the item — and the honest response is to surface it and abstain, not
to average it into a confident-looking number. That mirrors the house convention everywhere
else: `Decision.CANT_TELL` in campaigns (`src/eval_harness/campaign.py`), `cant_tell` in the
regression estimate, and `OracleResult.verdict = None` routing to the audit queue rather
than a guess.

## What changes

- Add a `PanelJudge`, registered as `panel` in `JUDGES`, that builds N member judges from
  config via the same registry the engine uses and aggregates their verdicts under an
  explicit, enumerated strategy (`median` default, `mean`, `majority`).
- Surface per-member verdicts and spread statistics in `JudgeVerdict.raw`; above a
  configured disagreement threshold, the panel abstains instead of reporting a synthetic
  consensus.
- Give `LLMJudgeScorer` an abstention-aware path so an abstention reaches results as
  `passed=None` rather than `passed=False`. Without it the panel's central signal inverts
  into a confident negative at the scorer boundary — see "The abstention seam" below.
- Degrade member failures to abstention: a raising member is recorded and excluded, and a
  panel below quorum abstains rather than fabricating agreement from the survivors.
- Make panel cost accounting honest: extend `build_budgeted_judge`
  (`src/eval_harness/agent_core_adapter/__init__.py:341-347`) to reserve budget and rate
  capacity per member call, not per panel call (see below).
- Spell out the panel's calibration obligations — panel-level κ versus human labels,
  pairwise member–member κ as a redundancy check, member diversity as reported config — so
  a council is advisory until a named calibration artifact authorises more.

## Scope / non-goals

- **Non-goal: a gate.** The panel is an evaluation instrument. It gates nothing, and under
  `extend-judge-calibration`'s rule it stays advisory unless a gating configuration names
  the calibration artifact that authorised it. Gates never run live evaluations
  (`docs/CHARTER.md` §3).
- **Non-goal: an orchestration framework.** The panel is one registered component fanning
  out in-process, exactly as `CompositeScorer` builds children via `SCORERS.create`
  (`src/eval_harness/scorers/__init__.py:148`). No new runner, no new loop.
- **Non-goal: a second calibration system.** The panel's κ obligations reuse
  `agent_core.golden.cohen_kappa` (`agent-core/agent_core/golden.py:144`). No new math, no
  YAML knobs in `agent_core`, and the `eval_harness ⇎ flow_corpus` airgap is not amended —
  the κ-gate machinery is cited as precedent, never imported.
- **Non-goal: engine or core-model changes.** `JudgeVerdict` (`src/eval_harness/core/types.py:134-140`)
  and the engine item loop are untouched; the panel satisfies the existing `Judge` Protocol
  (`src/eval_harness/core/interfaces.py:66-70`). CHARTER §4 invariant 1 holds without
  invoking the ADR 0031 exception.
- **Non-goal: threading per-member *detail* into `ScoreResult`.** `LLMJudgeScorer` keeps only
  `verdict.score` and `verdict.reasoning` today
  (`src/eval_harness/scorers/__init__.py:208-218`); `verdict.raw` — where the per-member
  breakdown lives — is dropped before results. Surfacing that breakdown downstream is
  deliberate follow-up surface, not smuggled in here. **The abstention *signal* is a
  different matter and is in scope** — see below.
- **Non-goal: a registry alias.** `FROZEN_ALIAS_MAP["judge"]` is asserted by exact equality
  (`tests/_matrix_coverage.py`), so `panel` ships alias-free; `council` as an alias would be
  a red gate until frozen deliberately, and earns nothing.

## The budget seam, and why the naive panel breaks it

`BudgetedJudge` reserves cost **once per `evaluate()` call** — a single
`self._ledger.record(self._cost_per_call)` under a lock
(`src/eval_harness/agent_core_adapter/__init__.py:326`) — and the F-030 sliding-window rate
limiter counts the same way. A panel that fans out to N members inside one `evaluate()`
would therefore under-charge the judge budget and under-count the rate limit by a factor of
N: the cap an operator configured for one provider call would silently authorise five.

The resolution keeps the wrapper outermost and additive: `build_budgeted_judge` reads an
optional duck-typed `calls_per_evaluate` attribute on the inner judge (absent → `1`, the
status quo for every existing judge) and scales its reservation accordingly; `PanelJudge`
exposes `calls_per_evaluate = len(members)`. This also documents *why the panel is a judge
and not a scorer*: components that call providers outside the `Judge` seam run outside the
`judge_budget`/rate-limit guard entirely, as `AutoevalsScorer` already warns
(`src/eval_harness/scorers/__init__.py:242-245`).

## The abstention seam

A panel that abstains is making the claim "we cannot tell". Today that claim cannot survive
the trip to a result: `LLMJudgeScorer.score` sets `passed=verdict.score >= self.threshold`
(`src/eval_harness/scorers/__init__.py:214-217`) with no `None` path, so an abstention lands
as `passed=False` — indistinguishable from a confident judgement that the output was bad.
That inverts the signal this component exists to produce.

Everything downstream is already built for it, which is why the fix is small rather than
structural: `ScoreResult.passed` is `bool | None` (`core/types.py:129`), `AutoevalsScorer`
already emits `value=self.on_skip, passed=None` when its evaluator declines
(`scorers/__init__.py:307-313`), `EvalEngine._aggregate` already excludes `None` from
`pass_rate` and returns `None` when every verdict is `None` (`engine.py:210-211`), and
`CompositeScorer` already ignores `None` children rather than failing on them. One scorer is
the sole blocker, and it is a protected path.

## Impact

- New judge in `src/eval_harness/judges/` at the root **96%** coverage floor; registration
  creates the ADR 0032 matrix obligation for kind `judge` (dims M1, M2, M3, M6 per
  `tests/_matrix_coverage.py`) plus regenerated `tests/plugin_registry_baseline.json`,
  `tests/public_surface_baseline.json`, and `docs/matrix-coverage.md`.
- Additive change in `src/eval_harness/agent_core_adapter/` (unprotected) for per-member
  budget accounting.
- Config stays a bare `ComponentSpec {type, params}` (`src/eval_harness/config/models.py:17-21`);
  fully optional and additive, so `SCHEMA_VERSION` is unchanged.
- **Protected paths:** `src/eval_harness/judges/**`, `tests/**`, `features.yaml`,
  `scripts/validations/**` — implementation PRs carry the `eval-change-approved` label. This
  proposal package touches none of them.

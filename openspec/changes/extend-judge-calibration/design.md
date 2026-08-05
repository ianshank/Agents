# Design: extend-judge-calibration

## Placement

| Concern | Home | Why |
|---|---|---|
| Probe math (order flip, verbosity delta, self-preference rates) | `agent-core/agent_core/` | Dependency-free and importable from both sides of the airgap |
| Consumption by the harness | `src/eval_harness/agent_core_adapter/` | Existing declared edge `agent_core_adapter: [agent_core, config, core]` |
| Consumption by the regression detector | `behavioral_regression` direct import | Existing declared edge `behavioral_regression: [agent_core, flow_corpus]` |

No new component edge is declared and `architecture.yaml` is not edited. The airgap holds
(`docs/plans/agent-eval-coverage/REVIEW.md` §B5).

`agent_core` stays config-file-free: probe tunables are frozen dataclass fields, matching
`CalibrationConfig` and `GoldenConfig`.

## What is reused, and what is not

**Reused:** the deterministic `seed:item_id` hash split and `evaluate_on_split`'s held-out
discipline from `agent_core/golden.py`; `flow_corpus.oracles.kappa_gate.validate_oracle`'s
indeterminate-pair exclusion and power gating, via `behavioral_regression`'s existing wrapper.

**Not reused:** `GoldenItem` itself. It is `(item_id, text, label ∈ {0,1}, domain, source)` — a
binary-label corpus for the merge gate with no notion of an answer *pair*. A pairwise, order-swapped
corpus is a new type. The externally proposed plan claimed the whole golden-set machinery was
reusable; only the splitter is (`REVIEW.md` §B9).

## Report

A versioned `JudgeCalibrationReport` carrying: percent agreement, Cohen's κ, order-flip rate,
verbosity preference delta, self-preference breakdown by model family, calibration confidence
intervals, and held-out sample size with power status.

Canaries known to be equal, clearly better and clearly worse are included, so a judge that has
stopped discriminating at all is detected rather than scoring a flattering κ on an easy corpus.

## Gating

A judge is advisory unless agreement, power **and** every configured bias tolerance pass. Gating
configuration must name the calibration artifact ID that authorised it, so a gate decision is
traceable to a specific calibration run rather than to "a judge that was validated at some point".

This mirrors the merge gate's existing posture: `is_trustworthy` must hold before `tau` is derived,
and a metric that measured nothing must not pass (ADR 0029).

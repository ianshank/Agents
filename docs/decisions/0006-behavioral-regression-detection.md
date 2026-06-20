# 0006 — Behavioral regression detection (calibrated, offline, fail-safe-to-escalate)

- Status: **Accepted.** Ships as a self-contained sibling package with a 95%-branch test
  suite, an offline F-016 validation, and an opt-in CI workflow.
- Date: 2026-06-20
- Related: F-016, `agent_core/calibration.py`, `agent_core/merge_gate.py`,
  `flow_corpus/oracles/kappa_gate.py`, `flow_corpus/validation/resampling.py`,
  `flow_corpus/canary/separation.py`, ADR 0005 (calibrated merge gate).

## Context

Shipping a model or prompt change "with confidence" turns on contested behavioral questions
("did v2 get more sycophantic?", "did web search get worse?") whose oracles have no clean
ground truth. The worst failure mode is **confident wrongness** — telling a launch "you're
fine" when it isn't. We need a runnable artifact that detects such a regression with
*calibrated* confidence, proves its own judge isn't fooling itself, names where its
measurement stops working, and turns the messy question into a defensible ship decision.

The repository already contains every statistical primitive this needs (Wilson/Brier/
reliability/AUROC/isotonic in `agent_core.calibration`; `cohen_kappa`; the oracle-κ gate,
bootstrap delta CI, and discrimination canary in `flow_corpus`; the layered
fail-safe-to-escalate decision in `agent_core.merge_gate`). The feature is an orchestration
+ scenario layer over them, not new statistics.

## Decision

Ship a new sibling package **`behavioral-regression`** (`behavioral_regression`) that composes
those primitives into a 7-beat pipeline — generate → judge → validate → detect → canary →
gate → report — with these invariants:

1. **Gate on calibrated confidence, fail-safe-to-escalate.** `decide_ship` mirrors
   `merge_gate.decide`'s layering: ESCALATE whenever the apparatus is untrusted (canary not
   separated, judge not validated, or the detector can't tell), HOLD a real regression, and
   SHIP only a validated, separable, below-risk change. The default is always ESCALATE.
2. **Validate the oracle before it gates.** The contested judge is *advisory* until it clears
   `min_judge_kappa` against a human-label set with enough co-determinate power
   (`flow_corpus.oracles.kappa_gate.validate_oracle`). An unvalidated judge cannot gate.
3. **Emit uncertainty, not verdicts.** The detector reports a probability with a Wilson CI and
   a bootstrap delta CI, plus an explicit `cant_tell` bucket (delta CI includes zero, or below
   power) — knowing where the measurement stops working is part of the product.
4. **Treat the canary as load-bearing.** A known-regression arm and a known-null arm are run
   through the full path; if the detector can't separate them, the gate escalates. The canary
   is built from the v1 baseline so a high-drift run can't collapse it.
5. **No hard-coded values.** Every threshold lives on the frozen, versioned `BRConfig`;
   decision logic reads only from it. Configs round-trip with migration.
6. **Offline and deterministic.** The default path uses a seeded synthetic generator and a
   deliberately-imperfect `SyntheticJudge`; a run is byte-reproducible from `(BRConfig, seed)`
   and touches no network (asserted by a socket-blocking test and the F-016 validation).

### Placement & dependencies (and the airgap)

`behavioral_regression → flow_corpus → {flow_protocol, agent_core}` — acyclic, and the package
**never imports `eval_harness`**, preserving the structural airgap the drift gate enforces. It
sits at the same layer as `flow_corpus`.

### Reuse vs. promotion (D2)

The plan considered *promoting* `bootstrap_delta_ci` and `validate_oracle` from `flow_corpus`
into `agent_core` (with re-exports). We chose instead to **depend on `flow_corpus` directly**:
it is fully backwards-compatible (touches no existing package's code, so F-013/F-014 are
unaffected), keeps the graph acyclic, and still reuses the proven, tested implementations
rather than duplicating them. Promotion remains a clean future refactor if a second consumer
of those helpers appears outside the `flow_corpus` dependency cone.

### Dashboard & live model (D3/D4)

The deterministic JSON report (+ a self-contained inline-SVG HTML reliability diagram) is the
tested source of truth. A thin **Streamlit** shell renders the same report behind the
`[dashboard]` extra — never a source of truth, never on the offline/test path. An optional
live **`AnthropicJudge`** lives in `eval_harness.judges` behind the `[anthropic]` extra; the
sibling stays offline and the harness layer is the only one that imports both. Per the
project's Claude/Anthropic guidance, the judge's model id is config-driven (default
`claude-opus-4-8`) and `temperature` is omitted by default — sampling parameters are rejected
(HTTP 400) on Opus 4.8/4.7.

## Consequences

- A product team can answer a contested behavioral question with a calibrated, honest,
  defensible ship/hold/escalate decision, runnable offline.
- `behavioral-regression` adds a third top-level package to the drift manifest and a CI
  workflow; the airgap check must keep `eval_harness ↔ behavioral_regression` edges absent.
- The synthetic judge's imperfection is deliberate and load-bearing; if it were made too clean,
  the calibration and canary would be meaningless — property tests guard non-triviality.

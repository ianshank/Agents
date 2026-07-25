# agent_core

Deterministic **control & calibration core** for the research-assessment agent
designed earlier in this thread. It implements the parts that are pure logic and
carry the most design risk — the two-gate verifier loop, the per-run cost
budget, and the calibration measurement stack — and exposes typed **Protocol
seams** for the I/O-bound nodes (verifier, retrieval, LLM, cost model) instead of
faking them.

## Why this scope
A framework that stubbed all nine architectural containers would be mostly
unused, untested scaffolding. Instead this package builds the testable core to
production quality and lets you inject real implementations through stable
interfaces. See `GAP_ANALYSIS.md` for exactly what is built vs. seamed vs. absent.

## Design properties
- **No hardcoded values** — every threshold lives in `agent_core.config`
  dataclasses with documented defaults; logic reads config.
- **Dynamic / open-closed** — stop rules are registrable `StopCondition` objects;
  add one without touching the loop.
- **Backwards compatible** — configs are versioned and auto-migrated
  (`agent_core.version`); a deprecated-alias shim keeps renamed symbols working.
- **Reusable** — the loop is generic over `CycleRunner` / `CostEstimator`; the
  calibration metrics are plain functions over sequences.
- **Observable** — config-driven logging plus a `debug_span` tracer.

## Install & test
```bash
cd agent-core               # monorepo subfolder; run all dev commands from here
pip install -e ".[dev]"     # editable install + pinned toolchain (zero runtime deps)
python -m pytest --cov      # property-based incl.; branch coverage gated at 95%
ruff check agent_core tests
ruff format --check agent_core tests
mypy agent_core             # strict
```

## Enforced safety guarantees (post peer review)
- A cycle is granted a hard **allowance**; `BudgetLedger.record` raises
  `BudgetExceededError` if a runner exceeds it, so an inaccurate `CostEstimator`
  can no longer breach the reserve — the run finalises `BUDGET` with
  `overspent=True` and the ledger never exceeds `cap`.
- `LoopController` enforces an **absolute cycle limit** independent of the
  injected gates, guaranteeing termination even under gate misconfiguration
  (`StopReason.ABORTED`).
- `BudgetLedger` is thread-safe (lock around all mutation).

## Wiring a real run
```python
from agent_core import (
    FrameworkConfig, BudgetLedger, LoopController, CycleState,
)

cfg = FrameworkConfig.from_dict({
    "budget": {"cap_units": 600_000, "reserve_fraction": 0.15},
    "loop":   {"max_cycles": 5, "convergence_epsilon": 0.05},
})

class MyVerifier:          # implements CycleRunner
    def run(self, state): ...     # -> CycleResult(cost, new_unresolved, max_conf_delta, new_evidence)

class MyEstimator:         # implements CostEstimator
    def project(self, state): ... # -> projected next-cycle cost

ctrl = LoopController(cfg, BudgetLedger(cfg), MyVerifier(), MyEstimator())
result = ctrl.run(CycleState(unresolved=("claim1", "claim2", "claim3")))
print(result.reason, result.cycles_completed, result.spent)
```

## Validating confidence labels
```python
from agent_core import evaluate_calibration, IsotonicCalibrator

report = evaluate_calibration(
    probs, outcomes, n_bins=10,
    ece_target=0.05, mce_target=0.12, auroc_target=0.80,
    # Opt-in guards; these defaults (1 / False) reproduce the pre-guard behaviour.
    min_samples=30, require_discrimination=True,
)
# A calibrated-but-undiscriminating model fails on the AUROC target — but only when AUROC
# is *defined*. A slice with one outcome class or a constant predictor cannot evidence
# discrimination at all, so it is always named on report.degenerate (and logged); pass
# require_discrimination=True to make that fail the gate rather than pass it vacuously.

cal = IsotonicCalibrator().fit(train_probs, train_outcomes)   # fit on a held-out split
recalibrated = [cal.predict(p) for p in test_probs]
```

## Layout
```
agent_core/
  config.py        versioned config + validation + migration entry
  version.py       schema version, migrations, deprecated_alias
  protocols.py     CycleRunner / CostEstimator / StopCondition + dataclasses
  budget.py        BudgetLedger (cap/reserve/ceiling/admission)
  stop.py          4 stop conditions + Gate (first-true-wins)
  loop.py          LoopController (admission gate -> cycle -> outcome check)
  calibration.py   bins, ECE, MCE, Brier+Murphy, AUROC, Wilson, selective, isotonic
  ppi.py           PPI++ interval (fail-closed to Wilson), pearson_r, effective-N multiplier
  logging_util.py  config-driven logging + debug_span
  sanitize.py      RuleSanitizer, Sanitizer protocol, build_sanitized_claims
  golden.py        GoldenSet, split (hash-bucket), cohen_kappa, evaluate_on_split
  recalibration.py TemperatureScaler, CalibratorRegistry, make_calibrator
  async_loop.py    AsyncLoopController, ParallelClaimRunner (semaphore-capped)
  persistence.py   save_run, load_run, calibrator round-trip serialization
  merge_gate.py    GatePolicyConfig, decide() (REJECT->ESCALATE->AUTO_MERGE), threshold_for_risk
  outcome_store.py OutcomeStore (append-only JSONL), BinningCalibrator, build_domain_models
  outcome_labeller.py passive revert/CI-failure/timeout-clean labels (real detectors)
  audit_sampler.py unbiased stratified sampling (+ inclusion propensity) + HUMAN_AUDIT verdicts
  proxies.py       pluggable proxy extractors (raw confidence / passive label / external)
  proxy_eval.py    proxy-vs-audit correlation, marginal AND conditional on gated subsets
  calibration_report.py  agent-records report (wilson | ppi++); report_types + _render split
  merge_gate_ci.py CI entrypoint (exit 0/10/20; 2 = usage/bad input, 1 = internal), audit-logged
  detectors.py     GitRevertDetector, GitHubChecksFailureAttributor, resolve_repo (fail-safe)
  timeutil.py      parse_iso8601 (Z-tolerant, UTC-default)
tests/             688 tests across all modules
```

## Calibrated merge gate (F-010, default-off)
A pure, deterministic merge-decision subsystem (ADR 0005). `merge_gate.decide()` is REJECT on
mechanical failure → ESCALATE on protected paths → calibrated trust (risk-derived `tau` + health
floors + per-bin Wilson floor) → AUTO_MERGE. Outcomes are labelled by **real** detectors —
reverts from `git log`, CI failures from GitHub Actions check-runs via `gh api` — all
timeout-bounded and failing safe. Auto-merge stays off unless `ENABLE_CALIBRATED_AUTOMERGE` is
set and a populated, human-audited outcome store has earned it.

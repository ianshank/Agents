# behavioral-regression

> *"Did Claude get more sycophantic between v1 and v2?"* — a runnable, calibrated, honest answer.

A self-contained sibling package that detects a contested **behavioural regression** between
two model versions with **calibrated confidence**, proves its own judge isn't fooling itself,
shows where its measurement stops working, and gates **ship / hold / escalate**
(fail-safe-to-escalate). The default path is **offline and deterministic** — no network, no
live model — so a run is byte-reproducible from `(BRConfig, seed)`.

## The pipeline (7 beats)

```
BRConfig + seed
  → PairedResponseGenerator        seeded synthetic v1/v2 responses (offline)
  → SyntheticJudge                 a deliberately-imperfect contested judge
  → validate_judge (κ + power)     measure the judge vs human labels before trusting it
  → RegressionDetector             p(regression) + Wilson/bootstrap CI + "can't tell" bucket
  → run_canary                     inject a known regression + known null; assert separation
  → decide_ship                    SHIP / HOLD / ESCALATE, fail-safe-to-escalate
  → RegressionReport               deterministic JSON + self-contained HTML reliability diagram
```

## Reuse, not reinvention

The statistics are **reused** from the monorepo's proven primitives, never re-derived:

| Step | Reused symbol | Source |
|------|---------------|--------|
| Wilson CI, reliability bins, Brier | `wilson_interval`, `reliability_bins`, `brier_score`, `brier_decomposition` | `agent_core.calibration` |
| Bootstrap CI on the v1→v2 delta | `bootstrap_delta_ci` | `flow_corpus.validation.resampling` |
| Oracle κ-validation + power gate | `validate_oracle` (over `cohen_kappa` + `is_directional_only`) | `flow_corpus.oracles.kappa_gate` |
| Ship/hold/escalate layering | pattern of `agent_core.merge_gate.decide` | `agent_core.merge_gate` |

Dependency direction is acyclic: `behavioral_regression → flow_corpus → {flow_protocol, agent_core}`.
This package never imports `eval_harness` (the airgap); the optional **live** `AnthropicJudge`
lives in `eval_harness.judges` and is wired in only by the harness layer.

## Run

```bash
pip install -e ./agent-core -e ./flow-protocol -e ./flow-corpus -e ./behavioral-regression

# Deterministic offline run → JSON + HTML reliability diagram
bregress --seed 7 --out out/report.json --html out/report.html
python -m behavioral_regression --seed 7 --set v2_sycophancy_mean=0.55

# Optional Streamlit shell over the same report
pip install -e './behavioral-regression[dashboard]'
streamlit run behavioral-regression/behavioral_regression/dashboard.py
```

```python
from behavioral_regression import BRConfig, run_pipeline

report = run_pipeline(BRConfig(v2_sycophancy_mean=0.55), seed=7)
print(report.decision.value)        # ship | hold | escalate
print(report.to_dict()["estimate"]) # p_regression, CIs, cant_tell, ...
```

## No hard-coded values

Every threshold lives on the frozen `BRConfig`; decision logic never embeds a literal.
Override via construction (`BRConfig(ship_risk_target=0.4)`) or `--set key=value`. Configs are
versioned and round-trip through `to_dict`/`from_dict` with migration, so persisted configs stay
backwards-compatible.

## Test

```bash
cd behavioral-regression
HYPOTHESIS_PROFILE=ci pytest --cov --cov-report=term-missing   # ≥95% branch coverage
ruff check behavioral_regression tests && ruff format --check behavioral_regression tests
mypy behavioral_regression
```

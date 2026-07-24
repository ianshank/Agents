# flow-corpus

> A **calibration corpus of agentic flow variants** — specimens, task suites,
> oracles, and the validation runner that turns them into calibrated signal.

`flow-corpus` supplies the offline, deterministic raw material used to calibrate
and validate agentic-flow judgement in this monorepo. It is fully synthetic and
firewalled from any live outcome data, so a corpus run is byte-reproducible.

## Why this scope

Calibrated evaluation needs a controlled population with known properties
(injected regressions, known nulls, held-out partitions). `flow-corpus` builds
and validates that population deterministically, then exposes it through the
airgap contract in [`flow-protocol`](../flow-protocol/README.md). Downstream,
[`behavioral-regression`](../behavioral-regression/README.md) composes these
primitives into a ship/hold/escalate gate.

Dependency direction is acyclic and enforced:
`flow_corpus → {flow_protocol, agent_core}`. It never imports the harness.

## What's in it

| Area | Module(s) | Role |
|---|---|---|
| Specimens & suites | `specimens/`, `suites/`, `data/suites/` | the flow variants and the task suites over them |
| Mutation & canaries | `mutation/`, `canary/` | inject known regressions / known nulls to test separation |
| Partitioning | `partition.py`, `holdout/`, `keying/`, `pinning.py` | deterministic, keyed train/holdout splits |
| Oracles | `oracles/` | κ-validated verdict oracles (with a power gate) |
| Cross-checks & policy | `crosscheck/`, `policy/` | independent corroboration and selection policy |
| Validation runner | `validation/` | resampling / bootstrap CIs over corpus results |
| Config & versioning | `config.py`, `version.py` | validated `*Config` (no hard-coded values), versioned + migrated |

See [`CHANGELOG.md`](CHANGELOG.md) and [`GAP_ANALYSIS.md`](GAP_ANALYSIS.md) for
release history and the built-vs-seamed map.

## Install & use

```bash
# Editable installs, in dependency order:
pip install -e ./agent-core -e ./flow-protocol -e ./flow-corpus
```

```python
from flow_corpus.config import CorpusConfig      # every threshold is a config field
# build/validate the corpus via the validation runner (see flow_corpus/validation/)
```

## Test (run from this directory)

```bash
cd flow-corpus
pip install -e '.[dev]'
HYPOTHESIS_PROFILE=ci pytest --cov            # ≥95% branch coverage floor
ruff check flow_corpus tests && ruff format --check flow_corpus tests
mypy flow_corpus                              # strict
# or the generated one-shot gate:
bash scripts/quality-gate.sh all
```

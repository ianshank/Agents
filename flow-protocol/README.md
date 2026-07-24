# flow-protocol

> The **versioned contract surface** between the flow-calibration corpus and the
> validation harness — the single import allowed across the airgap.

`flow-protocol` is the smallest package in the monorepo and deliberately so. It
defines the frozen data contract that the corpus (`flow-corpus`) produces and the
validation/behavioral layers consume, so neither side has to import the other.
Its **only** runtime dependency is `pydantic>=2`.

## Why this scope

The corpus and the harness are airgapped on purpose (see
[`docs/CHARTER.md`](../docs/CHARTER.md) and
[`docs/c4_architecture.md`](../docs/c4_architecture.md)). A shared, versioned
contract lets them evolve independently while a change to the wire format stays
explicit and reviewable. This package **must never** depend on the corpus or the
harness — that acyclic direction is an invariant.

## What's in it

- Frozen Pydantic v2 models: `FlowResult`, `OracleResult`, `ConfidenceChannel`
  (`flow_protocol/contract.py`).
  - `raw_confidence` is optional — outcome-only flows need not fabricate one.
  - `OracleResult.verdict` is `bool | None`, where `None` denotes an
    indeterminate (abstained) verdict.
  - `ConfidenceChannel.per_step` validates each value into `[0, 1]`.
- `PROTOCOL_VERSION` — the wire-contract semver, tracked **separately** from the
  distribution version — plus a `migrate_protocol` chain (mirrors
  `agent_core.version`) so additive contract bumps stay backwards-compatible.

See [`CHANGELOG.md`](CHANGELOG.md) for the release history.

## Install & use

```bash
pip install -e ./flow-protocol            # or `pip install flow-protocol`
```

```python
from flow_protocol import FlowResult, OracleResult, ConfidenceChannel, PROTOCOL_VERSION

result = FlowResult(...)                   # frozen; validated at construction
```

## Test (run from this directory)

```bash
cd flow-protocol
pip install -e '.[dev]'
pytest --cov                               # ≥95% branch coverage floor (100% today)
ruff check flow_protocol tests && ruff format --check flow_protocol tests
mypy flow_protocol                         # strict
```

The package's public surface is frozen by a committed
`tests/public_surface_baseline.json` (a removed/renamed export fails CI).

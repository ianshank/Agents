# Design: add-fixture-replay

## Contracts

New package `eval_harness.replay` (ADR 0019: do not grow `engine.py` / `comparison.py` /
`core/types.py` past 500 lines). `trajectory_from_dict` lives next to envelope parse
helpers.

```python
ENVELOPE_SCHEMA_VERSION = "1.0.0"  # independent of SCHEMA_VERSION and TRAJECTORY_SCHEMA_VERSION

@dataclass(frozen=True)
class ReplayEnvelope:
    envelope_id: str
    recorded_run_id: str
    item_id: str
    recorded_at: str  # ISO-8601
    environment: str
    agent_version: str
    input_hash: str
    output_hash: str
    trajectory: AgentTrajectory
    # optional: prompt/model hashes, StateSnapshot, tags, payload_refs, recorded output
```

Unknown keys raise (`ReplayError`). Vendors stay export-only.

## Target

`@TARGETS.register("replay")`. `run(self, item)` takes only the item. Archive path,
mode (`exact` | `counterfactual`), override map, and `--from-span` are constructor
params (YAML `target.params` or CLI). Missing envelopes degrade to `TargetOutput.error`
(ADR 0038). Corrupt JSONL fails closed.

Counterfactual pins recorded steps and replaces matching `tool_observation` /
`tool_error` content after `from_span`. A value `error:<msg>` becomes a `tool_error`
step. Dotted `module:attr` override values are ADR 0039 allowlisted callables.

## CLI

`eval-harness replay --archive … --mode exact|counterfactual` scores with
`trajectory_in_order` and `trajectory_recovery` (defaults on `ReplayConfig`). Slice
pass-rates group `item.metadata['replay_tags']`. HTML is an ordered step table, not a
JS waterfall.

## Architecture

```yaml
replay: [eval_harness.replay]
replay: [core, plugins]
plugins: [..., replay]
cli: [..., replay]
```

The `plugins ↔ replay` cycle matches `targets`.

# 0025 - Outcome-record forward compatibility: unknown fields are not corruption

**Status**: Accepted
**Date**: 2026-07-24

## Context and Problem Statement

Two readers of `merge_outcomes.jsonl` hold contradictory parse contracts, and the
contradiction is reachable in normal operation.

`agent_core.store_sync` deliberately tolerates a line it cannot parse. `_parse_line`
(`agent-core/agent_core/store_sync/serialization.py`) names the exact scenario:

> A malformed line or one carrying fields this reader doesn't know (an upgraded writer
> during a rolling upgrade) must NOT crash the pipeline — and must NOT be silently
> dropped either, or a subsequent push would delete it from the data branch. Opaque
> lines are preserved verbatim.

`agent_core.jsonl` is deliberately strict, and says so:

> Strict by design: a malformed line raises, because an append-only audit store with a
> corrupt line is a store whose integrity guarantee is already gone — silently skipping
> would hide that.

Both rationales are correct for the failure they guard against. The defect is that
`OutcomeRecord(**json.loads(line))` cannot tell them apart: an **unknown extra key** and
a **missing required key** both raise `TypeError`. So the mechanism built to survive a
rolling upgrade produces exactly the record that breaks every other consumer.

Reproduced on a two-line store, one line carrying a field from a hypothetical newer
writer:

```
store_sync:    parsed=1 opaque=1
OutcomeStore:  TypeError: OutcomeRecord.__init__() got an unexpected keyword argument 'future_field'
```

Blast radius once such a line exists on the data branch: `merge_gate_ci` exits 1 in both
the gate and the shadow job, so **every PR fails**; `outcome_labeller`, `audit_sampler`,
and `merge_seed` have no handler at all and traceback. The store is append-only and
shared across versions, so this is a question of when, not whether.

Note the repo already solved the *backward* direction: `OutcomeRecord.agent_version`
was added in 1.3.0 with a default so "pre-1.3.0 JSONL lines (no field) still load"
(pinned by `test_record_loads_pre_1_3_0_json_without_agent_version`). Only the forward
direction — an older reader meeting a newer writer — was left open.

## Decision

Distinguish **additive schema evolution** from **corruption**, rather than treating every
unexpected payload shape as the latter.

`OutcomeRecord.from_json` now:

1. **Raises on corruption, exactly as before** — malformed JSON, a non-object payload, a
   missing required field, or a wrong type. The integrity guarantee `jsonl.py` protects is
   unchanged, and no strictness is traded away.
2. **Tolerates unknown extra fields**, dropping them from the in-memory record and logging
   them at WARNING with the offending key names. A well-formed record carrying a field a
   newer writer added is forward compatibility, not corruption.

Deliberately **not** changed:

- **`jsonl.iter_jsonl` stays strict.** It still propagates whatever the factory raises; the
  discrimination belongs in the record type that owns the schema, not in the generic line
  reader.
- **`store_sync._parse_line` keeps preserving such lines verbatim.** It calls the
  `OutcomeRecord` constructor directly rather than `from_json`, so it still classifies an
  unknown-field line as opaque and round-trips it byte-for-byte. This is the point: the
  *writer* must never silently rewrite a field it does not understand, while the *reader*
  must not crash on one. Both invariants now hold at once.

## Consequences

- **Positive** — a rolling upgrade no longer bricks the gate. An older reader degrades to
  ignoring fields it cannot use, which is the correct behaviour for a calibration consumer
  that only ever reads.
- **Positive** — the seam is now testable from both sides, and is tested: a store written
  through `store_sync` with an opaque line is read back through `OutcomeStore` in one test,
  which is the case neither module's suite previously crossed.
- **Positive** — unknown fields are logged rather than passed over in silence, so an
  operator sees that a newer writer is active against an older reader.
- **Negative** — an older reader silently loses the *semantics* of a newer field it drops.
  That is inherent to forward compatibility; the WARNING is the mitigation, and
  `store_sync` still preserves the data itself on the branch.
- **Negative** — a typo'd field name in a hand-edited record now logs instead of raising.
  Accepted: the store is machine-written, and the alternative is the outage above.

## Alternatives considered

- **Make `OutcomeStore.all()` skip unparseable lines.** Rejected: it would silently drop
  *corrupt* records too, so a truncated write would quietly shrink the calibration corpus —
  precisely what `jsonl.py`'s strictness exists to prevent.
- **Version every record and gate on `schema_version`.** Rejected as disproportionate: the
  store has one producer and a flat 8-field schema, and `FrameworkConfig` already owns
  versioned migration where it is warranted.
- **Leave it and document the hazard.** Rejected: the failure mode is a repo-wide PR outage
  triggered by an ordinary version skew, and the fix is ten lines.

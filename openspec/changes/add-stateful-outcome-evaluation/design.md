# Design: add-stateful-outcome-evaluation

## The adapter contract

```python
class StateAdapter(Protocol):
    def snapshot(self, ctx: RunContext) -> StateSnapshot: ...
    def evaluate(self, *, item: EvalItem, before: StateSnapshot,
                 after: StateSnapshot) -> StateEvaluation: ...
    def reset(self, ctx: RunContext) -> None: ...
```

`RunContext`, not `EvalContext` — the latter does not exist in this repository
(`docs/plans/agent-eval-coverage/REVIEW.md` §B4).

`runtime_checkable` `Protocol`, matching the four existing structural seams
(`core/interfaces.py`), so a fake in a test satisfies it by shape alone.

## Who owns the lifecycle

The **engine**, not the target. `TargetRunner.run(self, item)` takes no context parameter, so there
is no seam on the target to hang before/after capture on. Per attempt:

```
reset → snapshot(before) → target.run(item) → snapshot(after) → adapter.evaluate → scorers
```

This placement also satisfies CHARTER §4 invariant 4: the adapter is the narrow seam that does I/O,
and the state scorers stay pure functions over two snapshots handed to them as data.

## Implementation order

1. `StateSnapshot` representation (opaque, comparable, serialisable).
2. Adapter Protocol and registry.
3. Reset/isolation lifecycle in the engine, including the failure path.
4. Before/after capture.
5. Deterministic state scorer.
6. Policy-violation scorer.
7. In-memory adapter, then filesystem sandbox, then SQLite, then mock HTTP.
8. Fault-injection tests (adapter raises during snapshot, during reset, mid-run).
9. Integration with repeated-run reliability.

## Adapter scope for the first change

In-memory mapping, filesystem sandbox, SQLite transaction, in-process mock HTTP. All deterministic,
all offline — the offline suite must keep its zero-external-dependency property (CHARTER §3). No
production credentials and no domain adapters ship here; they arrive later behind the same seam.

## Failure semantics

An adapter that raises during `snapshot` or `evaluate` fails the item rather than being swallowed —
a state check that silently degrades to "no opinion" is worse than no state check, because the
suite still looks green. `reset` failures abort the run: continuing would score subsequent attempts
against contaminated state.

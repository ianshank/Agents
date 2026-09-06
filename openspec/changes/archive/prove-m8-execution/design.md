# Design: prove-m8-execution

## Placement

| Concern | Home | Why |
|---|---|---|
| Execution ledger | `tests/_m8_probe.py` (new) | Underscore-prefixed, matching the existing `tests/_matrix_coverage.py`/`tests/_e2e_matrix.py` precedent for policy modules that are not themselves test files |
| Execution census | `tests/_matrix_coverage.py::pipeline_execution_census()` | Sits beside the existing `pipeline_kinds()`, which stays and is diffed against, not replaced |
| Cell-level vacuity refusal | `tests/test_matrix_coverage.py` | Mirrors the existing census-level `test_an_empty_census_never_satisfies_the_floors_vacuously` |
| Judge `client=` seams | `src/eval_harness/judges/__init__.py` | Same module the constructors already live in; mirrors `ModelTarget`'s seam in `targets/model.py`, a different module of the same shape |
| Egress guard | `tests/conftest.py`, scoped by marker | The standard pytest fixture seam; scoping to the matrix suite avoids widening this change's blast radius |

No `architecture.yaml` edge changes: the ledger and census are test-only tooling, and the
judge seams are a constructor-signature change inside an already-declared component.

## The execution ledger

`Registry.create` (`src/eval_harness/core/registry.py:54`) is the single construction choke
point for all six registered kinds — every scorer, judge, dataset, target, sink, and state
adapter the engine ever builds passes through it, including `panel`'s member judges
(`JUDGES.create` per member, `judges/panel.py:73`) and `weighted`'s child scorers
(`SCORERS.create`, `scorers/__init__.py:148`). A context manager patches this one function for
the duration of a probed run:

```python
@contextmanager
def probe() -> Iterator[ExecutionLedger]:
    ledger = ExecutionLedger()
    original_create = Registry.create

    def patched_create(self: Registry[Any], name: str, params: dict[str, Any]) -> Any:
        instance = original_create(self, name, params)
        canonical = self.resolve(name)
        method_name = _PROTOCOL_METHODS[self.kind]
        ledger.wrap(instance, kind=self.kind, component=canonical, method=method_name)
        return instance

    with patch.object(Registry, "create", patched_create):
        yield ledger
```

`ExecutionLedger.wrap` replaces the named method on the *instance* (not the class, so
sibling instances of the same type are counted independently) with a counting proxy that
still calls through to the original implementation, then records `(kind, canonical, method)`
in a `Counter` on every call.

## Protocol method names are a checked declaration, not a free list

`_PROTOCOL_METHODS` is a literal `dict[str, str]` (`{"scorer": "score", "dataset": "load",
"target": "run", "judge": "evaluate", "sink": "emit", "state_adapter": "snapshot"}` —
exact names confirmed against `src/eval_harness/core/interfaces.py`). A module-level
assertion at import time cross-checks each entry against `getattr(Protocol, name)` on the
corresponding Protocol class, so a future rename of, say, `Judge.evaluate` fails the ledger's
own import rather than silently under-counting. This is the same "checked declaration" idiom
`MATRIX_KIND`/`MATRIX_COMPONENTS` already use (ADR 0032 rule 2), applied to method names
instead of component names.

`state_adapter` gets three tracked methods, not one (`snapshot`, `evaluate`, `reset`), since
all three are load-bearing per `StateAdapter`'s Protocol and the M6 floor's own reasoning
(design.md "Failure semantics" for `add-stateful-outcome-evaluation`: error paths in any of
the three are explicitly not incidental).

## Swallowed-error detection

`EvalEngine` catches a scorer exception and converts it into a failing `ScoreResult` with a
`"scorer error: "`-prefixed comment (`engine.py:224-231`) — correct behaviour for a genuinely
broken scorer, and exactly the mechanism that let a network-egressing judge report green
during this proposal's own verification. `_assert_no_swallowed_errors(result)` asserts, over
every `ItemResult` in an `RunResult`: no result *is* an exception, and no `ScoreResult.comment`
starts with the exact swallow marker string. This is a string-match against a marker the
engine itself owns and already emits — no new engine hook, no new result field.

## Egress guard

```python
@pytest.fixture(autouse=True)
def _matrix_suite_no_egress(request: pytest.FixtureRequest) -> Iterator[None]:
    if "matrix_offline" not in request.keywords:
        yield
        return
    original_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> object:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"matrix suite attempted network egress to {address!r}")
        return original_connect(self, address)

    with patch.object(socket.socket, "connect", guarded_connect):
        yield
```

Applied via a `matrix_offline` marker on the M8 test classes only — not repo-wide — so this
change's blast radius stays scoped to what it is meant to prove. Widening it is separate
scope (see proposal.md non-goals).

## Judge `client=` seams

`OpenAIJudge.__init__` and `AnthropicJudge.__init__` gain `client: Any | None = None` as a
trailing keyword-only-by-convention parameter (matching `ModelTarget.__init__`'s existing
positional-with-default placement, `targets/model.py:112-129`, so the two seams read the same
way to a future maintainer). Each constructor's `import openai`/`import anthropic` and real
client construction move inside `if client is None:`; when a client is supplied, the SDK
module is never imported, matching `ModelTarget`'s already-shipped pattern of keeping the
whole seam offline-testable without the extra installed at all.

`tests/public_surface_baseline.json` regenerates in the same PR — a protected path already,
so no split is attempted here; see `docs/plans/eval-evidence-integrity/PLAN.md`'s sequencing
risk on this exact point.

## What is reused, and what is not

- `Registry.create` and `Registry.resolve` (`core/registry.py`) — reused unchanged; the ledger
  only observes, it does not alter dispatch.
- `pipeline_kinds()` (`_matrix_coverage.py:744-771`) — kept unchanged, read by the new
  execution census as the "declared" side of a declared-minus-executed diff.
- The census-level vacuity guard's shape (`test_an_empty_census_never_satisfies_the_floors_vacuously`)
  — the cell-level refusal mirrors its structure, not its code (different granularity, same
  ADR 0029 lesson: "a check that measured nothing must not report a pass").
- `ModelTarget`'s `client=` seam and its docstring convention — copied verbatim in spirit for
  the two judge constructors, not reinvented.
- Not reused: `pipeline_kinds()`'s config-dict-reading approach is deliberately *not* extended
  to a 41-cell floor on the same semantics — that is the defect this change closes.

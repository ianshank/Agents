# Design: add-agent-trajectory-evaluation

## Contracts

Added to `src/eval_harness/core/types.py`. New value objects are `frozen=True`; the existing
`TargetOutput` is **not** frozen and its field order is **not** changed (ADR 0031 obligations 1–2).

```python
@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: Mapping[str, Any]
    call_id: str | None = None

@dataclass(frozen=True)
class TrajectoryStep:
    kind: Literal["model_decision", "tool_call", "tool_observation", "tool_error", "final"]
    timestamp_ms: int | None = None
    tool_call: ToolCallRecord | None = None
    content: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AgentTrajectory:
    steps: tuple[TrajectoryStep, ...]
    schema_version: str

@dataclass                                    # unchanged: mutable, existing field order
class TargetOutput:
    output: Any
    latency_ms: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trajectory: AgentTrajectory | None = None    # appended last
```

The externally proposed contract froze `TargetOutput` and reordered it to
`output, error, latency_ms, metadata`. Both are breaking: freezing breaks every existing mutation
site, and reordering breaks positional construction. `tests/test_backwards_compat_config.py` and
`tests/public_surface_baseline.json` exist to catch exactly this
(`docs/plans/agent-eval-coverage/REVIEW.md` §B2).

`AgentTrajectory.schema_version` is the trajectory payload's own version and is deliberately
**independent** of `eval_harness.version.SCHEMA_VERSION`, which versions the *config* schema and is
out of scope for feature branches (CHARTER §3).

## Serialisation

`RunResult.to_dict()` gains a trajectory block per item, emitted **only when
`output.trajectory is not None`**. A run with no trajectories therefore produces byte-identical JSON
to the pre-change harness (ADR 0031 obligation 4), which is asserted by test rather than assumed.

## Normalisation — `core/_trajectory.py`

A pure module: no I/O, no SDK imports, no clock or RNG access (CHARTER §4 invariant 4 — stateful I/O
lives in the narrow seams, not the pure components). It lives under `core`, whose declared
dependency set in `architecture.yaml` is empty, so it introduces no component edge.

Design decisions:

- **Tool names** are canonicalised through a configurable transform (default: strip surrounding
  whitespace and lowercase), so `Search` and `search` compare equal.
- **Arguments** are canonicalised recursively with stable key ordering, so mappings that differ only
  by insertion order compare equal. Nested mappings, sequences and `None` are all handled.
- **Ignored fields** are configurable per scorer, for volatile values such as request IDs and
  timestamps. Ignoring is applied after canonicalisation so it works at any nesting depth.
- **Duplicates are preserved.** Collapsing them would erase the precision and loop signal outright.
  Matching therefore operates on multisets, not sets.

## Scorers — `scorers/trajectory.py`

A new module rather than an addition to `scorers/__init__.py`: that file is already 316 lines and
`scripts/check_size_budget.py:45` hard-fails any source file above 500
(`docs/plans/agent-eval-coverage/REVIEW.md` §B6). `scorers/__init__.py` imports the module so the
`@SCORERS.register` decorators run, mirroring how `targets/__init__.py` imports `targets/model.py`.

Each scorer subclasses `Scorer` (`abc.ABC` — the documented CHARTER §4 invariant 3 exception) and
takes every threshold as a constructor parameter with a documented default, so nothing numeric sits
at a call site (CHARTER §4 invariant 5).

| Registered name | Verdict |
|---|---|
| `trajectory_exact` | same calls, same order, no extras |
| `trajectory_in_order` | reference calls appear in order; extras tolerated |
| `trajectory_any_order` | all required calls present; order ignored |
| `trajectory_precision_recall` | multiset overlap; precision and recall reported separately in `metadata` |
| `trajectory_step_efficiency` | actual steps against a configured budget |
| `trajectory_loop_detection` | repeated identical call runs above a configured threshold |
| `trajectory_recovery` | a `tool_error` step must be followed by a retry, a fallback, or a non-success terminal outcome |

### The not-applicable verdict

A missing trajectory yields `ScoreResult(value=<on_missing>, passed=None, comment=...)`. This reuses
the repository's established convention for a skipped scorer (`AutoevalsScorer.score`,
`scorers/__init__.py:301-308`) rather than introducing a third status enum, which would be a further
core-model change for no gain (`REVIEW.md` §B10).

`EvalEngine._aggregate` (`engine.py:200-217`) excludes `passed=None` from `pass_rate` but **includes
every value in `mean`**. `on_missing` is therefore a real operator-facing knob, defaulted and
documented, not an inert placeholder.

Note also that `EvalEngine._run_one` (`engine.py:157-165`) already converts a scorer exception into
`passed=False` unless `fail_fast` is set. The hazard a not-applicable verdict guards against is
therefore not a crash — it is a silent `0.0` fail on every text-only item.

## Capture stays target-owned

A target that knows how it called its tools constructs the `AgentTrajectory`. The harness does not
reconstruct trajectories from Langfuse spans: Langfuse is an export and observability sink, and
making it the canonical representation would put a network dependency on the offline evaluation
path, which CHARTER §3 forbids. Trajectory export to tracing backends is one-directional and
optional.

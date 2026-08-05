# Agent trajectory evaluation

Grading *how* an agent reached its answer, not only the answer. Shipped as F-051 under
[ADR 0031](decisions/0031-additive-core-model-extension-for-agent-evaluation.md).

## Why it exists

Before F-051 every built-in scorer read `TargetOutput.output` — the agent's own account of
what it did. An agent that replied "I searched the catalogue and found it" without calling
any tool scored identically to one that actually did. Langfuse tracing existed, but tracing
is not scoring: spans are exported for a human to look at and never enter a verdict.

## The contract

A target that uses tools attaches an `AgentTrajectory` to its `TargetOutput`:

```python
from eval_harness.core import AgentTrajectory, TargetOutput, ToolCallRecord, TrajectoryStep

trajectory = AgentTrajectory(steps=(
    TrajectoryStep(kind="tool_call", tool_call=ToolCallRecord("search", {"q": "widgets"})),
    TrajectoryStep(kind="tool_observation", content="3 results"),
    TrajectoryStep(kind="final", content="Found 3 widgets."),
))
return TargetOutput(output="Found 3 widgets.", trajectory=trajectory)
```

Step kinds are `model_decision`, `tool_call`, `tool_observation`, `tool_error` and `final`.

**Capture is target-owned.** The harness never reconstructs a trajectory from tracing spans
— that would put a network dependency on the offline evaluation path. Trajectory export to
Langfuse or Phoenix is one-directional and optional.

**Everything is optional.** A target that emits no trajectory behaves exactly as it did
before: existing scorers are unaffected, and `RunResult.to_dict()` omits the `trajectory`
key entirely, so historical result JSON is byte-identical.

## Reference trajectories

Matching scorers read the reference from `item.expected`, in any of three shapes:

```yaml
expected: ["search", "fetch"]                                    # names only
expected: [{name: search, arguments: {q: widgets}}, {name: fetch}]  # names + arguments
expected: {tool_calls: ["search", "fetch"], answer: "..."}       # alongside other fields
```

## The scorers

| Name | Grades |
|---|---|
| `trajectory_exact` | Same calls, same order, nothing extra |
| `trajectory_in_order` | Reference calls appear in order; extras tolerated |
| `trajectory_any_order` | All required calls appear; order ignored |
| `trajectory_precision_recall` | Multiset overlap; precision and recall reported separately, value is their F1 |
| `trajectory_step_efficiency` | Work done against a budget |
| `trajectory_loop_detection` | Repeated calls above a threshold |
| `trajectory_recovery` | Whether a failed tool call was recovered from or papered over |

The last three need no reference — they grade the path on its own terms.

**Pick the loosest mode that still expresses the requirement.** `trajectory_exact` is the
strictest and the least broadly applicable: most real tasks admit several correct paths, and
a suite built entirely on exact matching will fail agents that are simply doing something
reasonable and different. Reach for `in_order` or `any_order` unless the sequence really is
the specification.

### Precision and recall are reported separately, on purpose

They mean different things. Low precision is wasted or unsafe work; low recall is work left
undone. Both appear in `ScoreResult.metadata` alongside `matched`, `candidate_calls` and
`reference_calls`.

```yaml
scorers:
  - type: trajectory_precision_recall
    params: {pass_threshold: 0.8}
```

### Efficiency is independent of success

A trajectory can reach the right answer wastefully. The budget comes from
`item.metadata['step_budget']` when present, else the scorer's `budget` param, so a suite can
set a per-task budget without a scorer per task.

```yaml
scorers:
  - type: trajectory_step_efficiency
    params: {budget: 4, count: tool_calls}   # count: steps to include observations
```

### Recovery

A `tool_error` step is fine — tools fail. What fails the scorer is *claiming success anyway*.
After an error the agent must retry, fall back to another tool, or stop without claiming
success. Mark a non-success terminal step with `metadata={"failed": True}` (the key is
configurable via `failure_key`).

## Normalisation

Before comparison, tool names are stripped and lowercased, and arguments are canonicalised
recursively with stable key ordering, so `Search` and `search`, and `{a:1,b:2}` and
`{b:2,a:1}`, all compare equal. Sequence order *is* significant — argument order carries
meaning.

```yaml
params:
  case_sensitive_names: false   # default
  ignore_fields: [request_id, timestamp]   # dropped at any nesting depth
  compare_arguments: true       # false matches on tool name alone
```

`call_id` never affects identity: it is a provider correlation id, and including it would
make every trajectory unique.

**Duplicates are preserved.** An agent that calls the same tool eleven times has a loop and a
precision problem; collapsing duplicates would score it identically to one clean call.

## When there is no trajectory to grade

A trajectory scorer facing a text-only target returns `passed=None` with a comment — not a
failing `0.0`. `EvalEngine._aggregate` excludes `None` verdicts from `pass_rate`, so mixing
trajectory scorers into a suite with text-only targets does not silently drag the pass rate
to zero.

The emitted **value** does still enter the scorer's mean, which is why `on_missing` is an
explicit knob rather than a hidden constant:

```yaml
params:
  on_missing: 0.0   # default; the value recorded when there is nothing to grade
```

## Diagnostics

Comments report the *canonical* (normalised) tool names, because those are what the
comparison actually used. A reference written as `Search` is reported as `search` under the
default config. This is deliberate: a diagnostic should never imply a match was attempted on
a form that was not.

## What this does not do

Repeated-run reliability (`pass@k` / `pass^k`), environment-state validation, and judge bias
calibration are separate capabilities with their own reviewed proposals under
`openspec/changes/`. See `docs/plans/agent-eval-coverage/PLAN.md` for the delivery order.

# Review: add-agent-trajectory-evaluation

**Reviewed:** the externally proposed `add-agent-trajectory-evaluation` change, re-verified against
the working tree at `b52c696`. Full findings across both source documents:
`docs/plans/agent-eval-coverage/REVIEW.md`.

## Verdict

The capability is correctly identified and correctly scoped, and its requirements and scenarios are
carried forward almost verbatim. Three of its stated contracts were wrong against the tree and are
corrected here; two repository gates it never mentioned would have failed the change on first push.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| B2 | Proposed `@dataclass(frozen=True) TargetOutput` reordered to `output, error, latency_ms, metadata` | Actual type is mutable, ordered `output, latency_ms, error, metadata`. Freezing breaks mutation sites; reordering breaks positional construction. `trajectory` is appended last, nothing else changes |
| B6 | Seven scorers tasked into `scorers/__init__.py` | That file is 316 lines and `check_size_budget.py:45` hard-fails above 500. New scorers go in `scorers/trajectory.py` |
| B7 | No baseline task | F-039 ships exact-equality guards; both `tests/*_baseline.json` need regeneration or CI fails immediately |
| B8 | "Regenerate `architecture.mmd` *if* imports change" | `architecture.yaml` is a protected path and the airgap's enforcement surface. Made an unconditional `[P]` task |
| B10 | Proposed a third `not_applicable` status | `ScoreResult.passed` is already `bool \| None`, and `AutoevalsScorer` establishes `passed=None` + comment for a skipped scorer. No core-model change needed |
| B1 | Core-model change against CHARTER §4 invariant 1, unacknowledged | Escalated and authorised by ADR 0031 before this proposal, per CHARTER §6 |

## Assumptions challenged

**Are trajectories compared after deterministic normalisation?** Yes, and it is a stated requirement
with its own scenarios, not an implementation detail. Without it the scorers would be flaky against
any target that varies argument key order.

**Can multiple valid paths pass?** Yes — this is why four modes exist rather than one. Exact
matching is the strictest and is expected to be the least used; `any_order` and
`precision_recall` exist precisely because most real tasks admit several correct paths. A suite that
only uses `trajectory_exact` is a misuse, and the documentation says so.

**Does a missing trajectory silently fail an item?** No, and this was the most consequential
correction. Under the original proposal a text-only target scored by a trajectory scorer would have
recorded `0.0 / failed` on every item. `passed=None` keeps it out of the pass rate — but the value
still enters the mean, so `on_missing` is exposed as a documented knob rather than hidden.

**Is tracing being confused with scoring?** The source analysis treated Langfuse tracing as partial
trajectory coverage. It is not: spans are exported for human inspection and never enter a verdict.
Capture stays target-owned, and Langfuse stays an export sink, so the offline evaluation path keeps
its zero-network property.

**Does duplicate preservation matter?** Yes, and it is the reason normalisation must not deduplicate.
An agent that calls the same tool eleven times has a loop and a precision problem; a set-based
comparison would score it identically to one clean call.

## Residual risk

- **`AgentTrajectory.schema_version` is a second version string.** It is deliberately independent of
  `eval_harness.version.SCHEMA_VERSION` (which versions config, and is out of scope for feature
  branches). The risk is that a future reader conflates them; the design document states the
  distinction explicitly and the field is documented at its definition.
- **`trajectory_recovery` encodes a judgement about what recovery means.** "Retry, fall back, or do
  not claim success" is defensible but not the only reading. It is a registered, replaceable
  component with configurable thresholds, so a suite that disagrees can substitute its own.
- **Coverage.** Seven scorers plus normalisation against a 96% floor is a large test surface. If the
  floor cannot be met the change should be split further rather than the floor lowered — weakening a
  gate to make a change pass is the exact failure mode `scripts/eval_protected_paths.py` exists to
  prevent.

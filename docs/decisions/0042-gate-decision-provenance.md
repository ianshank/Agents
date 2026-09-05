# 0042 - Gate-decision provenance: evaluate before emit, and per-rule advisory rules

**Status:** Accepted · **Date:** 2026-09-05
**Change:** `openspec/changes/add-gate-decision-provenance/` · **Feature:** F-062
**Supersedes:** nothing. **Amends:** nothing — see "Authority" below.

## Context

The quality gate's decision was never recorded anywhere.

`EvalEngine.run()` built the `RunResult`, emitted it to every sink, and returned
(`engine.py`). Only afterwards, in `cli.py`, did `evaluate_gate(config.gate, run)` run — purely to
choose an exit code. `RunResult` carried no gate field and `to_dict()` emitted none.

Three consequences, in ascending order of how much they mattered:

1. **Every sink was blind to the gate.** The `html_file` report, the JSON payload, the
   Langfuse/Phoenix/BrainTrust exports — none could say whether the run passed, which rule failed,
   or by how much. A run's own record did not contain its verdict.
2. **A soak could not be diffed.** "Run this non-blocking for two weeks and see what it would have
   done" needs the decisions to exist as data. They existed as two lines of CI stdout.
3. **The claim the gates protect was unevidenced.** "These metrics cannot be quietly weakened"
   rests on protected paths and CODEOWNERS, which is true — but no artifact showed what the gate
   actually decided on any given run, so the claim could be asserted and not demonstrated.

Separately: a gate rule either blocked or did not exist. A scorer whose threshold nobody had
calibrated had no home, which is the problem three queued scenario-evaluation changes each hit.

## Decision

### 1. Evaluate the gate inside `EvalEngine.run()`, before the sink loop

The verdict is attached to `RunResult.gate` and every sink sees it. The CLI then *reads*
`run.gate` rather than computing its own, so there is exactly one evaluation and the recorded
decision cannot disagree with the exit code.

`GateDecision` and `GateRuleRecord` live in `core/types.py`, not in `gating/`. `core` imports
nothing from its siblings; `gating` imports `core`. Defining the record in `gating` and naming it
from `RunResult` would have inverted that and created a cycle. `GateResult.to_decision()` is the
single place the two shapes are mapped.

Both new fields are appended last with defaults and omitted from `to_dict()` when unset — the
shape `TargetOutput.trajectory`, `ItemResult.attempt_index` and `RunResult.diagnostics` already
established. A run with **no gate configured** carries no decision and serializes byte-identically
to the pre-change payload.

### 2. Declare the `engine → gating` edge rather than working around it

`architecture.yaml` gains `gating` to `engine`'s dependency list. Considered and rejected:
threading a `gate_evaluator` in from the CLI so no edge appears. It only avoids the edge if the
*wiring* happens outside `engine.py`; wiring it in `from_config` imports `gating` anyway. Leaving
it to the CLI would have meant library callers using `EvalEngine.from_config` silently got no
decision — a correctness gap traded for a manifest line.

The edge is acyclic (`gating` depends on `config`, `core`, `reliability`, never on `engine`) and
is the layering the CLI already had. `drift_check.py` reports "Architecture matches the manifest."

An injectable `gate_evaluator` seam is kept regardless, defaulting to
`gating.default_gate_evaluator` — dependency injection with a sensible default, so an alternative
policy needs no second code path in the engine.

### 3. `GateRule.report_only` — per-rule, not whole-gate

An advisory rule is evaluated on the **same path** as a blocking one and differs only in where the
verdict is filed:

```python
(advisory if record.advisory else blocking).append(record.detail)
```

The partition is at the point a verdict is *filed*, never where it is *computed*. That makes
"advisory and blocking agree on the same run" true by construction rather than by test discipline.
Two evaluation paths would let them drift, and the drift would be invisible during exactly the
soak meant to establish trust in a threshold.

**Rejected: whole-gate exit-code neutralization at the workflow level.** It already ships —
`calibrated-merge-gate.yml` maps all three decision exit codes to job success — and it is the right
tool for soaking a gate as a whole. It is not sufficient here because it is all-or-nothing:
neutralizing the exit code makes *every* rule advisory, including calibrated ones, for the soak's
whole duration, with nothing in the artifact recording that it happened. Per-rule granularity is
what lets a live gate carry an experiment. Both mechanisms remain available.

**Rejected: a `--report-only` CLI flag.** A flag lets a red gate be silenced at the call site with
no diff in the repository showing it — the failure `coverage-floors.yaml` exists to close.
`report_only` lives in `config/`, a protected path, so promoting or demoting a rule is a reviewed act.

**Not relaxed:** `_require_at_least_one_bound`. A bound-less advisory rule is the same silent no-op
the validator was written to catch, wearing a label.

### 4. An advisory rule is not "gating" for `require_calibration_for_judge_gating`

The guard now counts only non-advisory rules. A judge-backed scorer under an advisory rule is
being *measured*, not trusted, and requiring a calibration artifact before it may be measured makes
calibration unreachable: the labelled corpus that produces the artifact is assembled from exactly
those advisory runs. The fail-closed refusal is unchanged for every rule that can block, and
promoting a rule re-arms it.

This is the state `extend-judge-calibration`'s "A judge SHALL remain advisory unless…" requirement
presumes. That change makes an uncalibrated judge unable to gate; this one gives it somewhere to
run in the meantime.

### 5. Sample-reduction failures follow the gate's own posture

`_item_error_failures` refuses to gate over a run whose sample was reduced by item errors. It is
filed as blocking when any rule can block, and as advisory when none can — an all-advisory gate
that started failing runs on sample reduction would be stricter than the blocking configuration it
was derived from.

## Authority

CHARTER §4 invariant 1 holds the engine, core models and registries unmodified when a capability
arrives through a registry. ADR 0031 carves a narrow exception **for agent evaluation** —
trajectory, repeated-run reliability, environment state.

A gate field on `RunResult` is additive and is an engine change, but it is not agent evaluation, so
it is outside that grant. This ADR is that authority, under ADR 0031's own obligations:
append-only fields, defaults reproducing current behaviour, no freezing, `SCHEMA_VERSION`
untouched, surface baselines regenerated.

`add-production-eval-flywheel/proposal.md` is the precedent for naming the gap rather than
proceeding on ADR 0031's strength: "It does **not** authorise this. Do not begin implementation on
the strength of it."

## Consequences

**Positive.** Every exported artifact carries the verdict, so a soak is diffable and the
reporting story is complete. An uncalibrated threshold has a home that does not require disarming
the calibrated ones. One evaluation, so the artifact and CI cannot disagree.

**Negative.** A new component edge, which is the more expensive thing to undo later. A run *with* a
gate now emits an extra `gate` key — additive, but a consumer asserting an exact key set will see
it. `report_only` is a new way to be wrong: a rule left advisory forever is a threshold nobody
enforces, and nothing in the mechanism notices. Promotion remains a human judgement backed by
evidence, deliberately.

**Neutral.** No new matrix rows: `gating` is not a `MATRIX_KIND` (`tests/_matrix_coverage.py`
`REQUIRED_DIMS`).

## Enforcement

`scripts/validations/F_062.py` (17 checks), `tests/test_gate_decision_provenance.py` (30 tests),
and the root suite's existing coverage floor of 96%. The provenance property is asserted through a
recording sink that observes `run.gate` already populated — asserting only that `run.gate` is set
after `run()` returns would pass even if attachment happened after the emit loop.

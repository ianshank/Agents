# Design: add-gate-decision-provenance

## The defect, in call order

```
engine.run()
  ├─ ... execute items, aggregate ...
  ├─ RunResult(...)                       core/types.py:176
  └─ for sink in self.sinks: sink.emit(run)   engine.py:411-412   ◄── sinks fire here
                                                                       with no verdict
cli._cmd_run()
  └─ gate = evaluate_gate(config.gate, run)   cli.py:92           ◄── verdict computed here
     print("QUALITY GATE: PASS" | "FAIL"); return 0 | 1              and then discarded
```

`evaluate_gate` is a pure function (`gating/__init__.py:92`) called from exactly one site. Its
result is used for two `print` calls and an exit code, then garbage-collected. Nothing durable ever
holds it.

So the `html_file` artifact the VP deck is generated from does not contain the gate's verdict, and
neither does any other sink's export.

## Fix: evaluate before emit

Gate evaluation moves inside `EvalEngine.run()`, ahead of the sink loop, and its result is attached
to the `RunResult`:

```python
run = RunResult(..., diagnostics=diagnostics)
if self.gate_config is not None:
    run.gate = evaluate_gate(self.gate_config, run)     # new, before emit
for sink in self.sinks:
    sink.emit(run)
return run
```

The CLI then reads `run.gate` instead of computing its own, so there is exactly one evaluation and
the recorded decision and the exit code cannot disagree. That equality is a requirement, not an
implementation detail: two evaluations would let the artifact say one thing and CI say another.

`RunResult.gate` is appended last with a `None` default and omitted from `to_dict()` when unset —
the ADR 0031 obligation-1 shape already used by `TargetOutput.trajectory`,
`ItemResult.attempt_index` and `RunResult.diagnostics`. A run with no gate configured serialises
byte-identically to today.

### Import direction

`architecture.yaml` declares `engine: [core, config, plugins, ...]` and `gating: [core, config,
reliability]`. `engine → gating` is a new edge, and `architecture.yaml` is a protected path
precisely so that edge gets human review rather than appearing silently. Two options for the
implementer, decided at implementation with the drift guard run both ways:

- **Declare the edge.** Simplest, one manifest line, reviewed.
- **Invert it.** The engine takes an optional `gate_evaluator` callable injected by
  `from_config`, so `engine` gains no import of `gating` at all and the CLI keeps wiring them
  together. Slightly more machinery, no new architectural edge.

The second is preferable if it costs nothing, because a new component edge is the more expensive
thing to undo. Do not decide it here by assertion — run `grimp` both ways and record which was
taken in `review.md`.

## Why this needs its own ADR

CHARTER §4 invariant 1 keeps the engine and core models unmodified when a capability arrives
through a registry. ADR 0031 grants a narrow exception **for agent evaluation** — trajectory,
repeated-run reliability, environment state. A gate field is an additive core-model and engine
change for a different purpose and is therefore outside that grant.

`add-production-eval-flywheel/proposal.md` is the precedent for saying so rather than proceeding:
"ADR 0031 authorises additive core-model and engine changes for agent evaluation. It does **not**
authorise this. Do not begin implementation on the strength of it." Same posture here, with a much
smaller ask: the ADR is written at land, under ADR 0031's own obligations — append-only fields,
defaults reproducing current behaviour, `SCHEMA_VERSION` untouched, surface baselines regenerated.

## Advisory rules: one path, two destinations

```python
for rule in gate_config.rules:
    verdict = _evaluate_rule(rule, aggregate, reliability)   # unchanged, shared
    if verdict.unmet:
        (result.advisory if rule.report_only else result.failures).append(verdict.record)
```

The partition happens where a verdict is *filed*, never where it is *computed*. This makes
"advisory and blocking agree on the same run" true by construction; the test then proves the
construction rather than chasing the property. Two evaluation paths would let them drift, and the
drift would be invisible during exactly the soak meant to establish trust.

## Why not whole-gate neutralization

It exists, it is cheaper, and it is the right tool for a different job — so it is worth being
explicit about why it is not this job.

`evaluate_gate` is called once and the exit code is decided in the CLI, so a workflow can run
`eval-harness run` and map its exit code to success. The repository already does this one level up:
`calibrated-merge-gate.yml:69-73` maps all three decision exit codes to job success and fails only
on internal errors.

The limitation is granularity. Neutralizing the exit code makes every rule advisory at once,
including calibrated ones. A soak on four new scorers would disarm the thresholds the repository
already trusts for the soak's whole duration — and nothing in the artifact would show that it had
happened. Per-rule `report_only` is what lets a live gate carry an experiment.

Both remain available: the workflow pattern for soaking a gate as a whole, `report_only` for
soaking one rule inside a live gate.

## Configuration

```yaml
gate:
  rules:
    - score: task_success
      metric: pass_power_k
      min: 0.95                # blocking, unchanged

    - score: testgen_mutation_score
      metric: mean
      min: 0.60
      report_only: true        # new optional field, default False
```

`report_only` defaults on `GateRule`, not at a call site (CHARTER §4 invariant 5), and is optional,
so `from_dict` stays strict and `SCHEMA_VERSION` is untouched. The existing
`_require_at_least_one_bound` validator (`config/models.py:224-229`) is deliberately **not**
relaxed.

## Recorded shape

`GateResult` gains `advisory: list[dict[str, Any]]`, and the persisted decision carries both
channels plus every rule that was met. Structured entries rather than formatted strings, for the
reason `RunResult.diagnostics` is `list[dict[str, str]]`: a soak's purpose is diffing the verdict
across runs, and a sentence cannot be diffed on the field that changed.

## Compiles down to

A numbered ADR at land (next free is 0042) recording: the evaluate-before-emit move, whichever
import direction the drift guard favours, the single-evaluation invariant, and the rejection of both
a CLI flag and harness-side whole-gate neutralization.

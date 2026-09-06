# Design: add-testgen-eval-matrix

## The seam: target executes, scorers read

The source plan put sandbox execution in the state adapters: "Sandbox execution uses the existing
`filesystem` and `sqlite` state adapters (F-060)." That is not what a `StateAdapter` is.
`src/eval_harness/state_adapters/__init__.py:28-36` says so directly — "the adapter does not intercept or observe the
target's execution, only what it is told." Its protocol is `snapshot(ctx)` plus `evaluate(...)`: it
captures world state *around* `target.run(item)` so a claimed side-effect can be verified. It is a
snapshot/diff seam, not an execution sandbox.

The correct seam already exists and needs no engine change:

```
callable target                     scorers (pure)
──────────────                      ──────────────
run generated suite in sandbox
collect / execute / mutate     ──►  TargetOutput.metadata["testgen_evidence"]  ──►  read only
                                    test_executability
                                    testgen_mutation_score
                                    testgen_green_on_correct
                                    requirement_obligation_recall
```

This is the `state_transition` pattern with the producer moved from the engine to the target:
"pure over data the engine already computed, no state comparison or I/O of their own"
(`src/eval_harness/scorers/state.py:1-13`). `TargetOutput.metadata` is already a `dict[str, Any]`
(`core/types.py:104-119`), so nothing in the core model changes and ADR 0031's additive-extension
authority is not needed.

Consequences worth stating, because they are the reason to prefer this shape:

- Scorers stay deterministic, so `repetitions > 1` measures the *target's* variance and not the
  scorer's — the property `add-repeat-reliability-metrics` had to correct a review to protect.
- Scorers stay offline, so they run in the zero-external-dependency suite unchanged.
- Each scorer is a few dozen lines, so the 20 owed matrix cells are cheap to fill honestly.
- Swapping the execution backend later touches one target, not four scorers.

## Evidence payload

```python
TargetOutput.metadata["testgen_evidence"] = {
    "collected": 12,                 # tests collected; 0 means non-executable
    "collection_error": None,        # str when collection raised
    "green_on_correct": {"ran": 12, "failed": 0},
    "mutants": {
        "generated": 40,             # non-equivalent, for this focal method
        "equivalent_excluded": 3,
        "covered": 22,               # non-equivalent AND reached by the suite
        "killed": 18,
    },
    "obligations_covered": ["OB-1", "OB-3", "OB-4"],
    "timed_out": False,
}
```

`raw = killed / generated`, `normalized = killed / covered`. Both denominators are in the payload so
a reader can recompute either, and neither scorer has to be trusted about which one it used.

## File layout, and why it is a package

`scripts/check_size_budget.py:46` sets `MAX_FILE_LINES = 500` as a hard gate. The existing
`scorers/trajectory.py` is 454 lines for seven scorers — about 65 lines each with the docstrings
house style requires. Four scorers fit in one module comfortably; the source plan's fourteen would
have been roughly 900 lines and failed the gate before review.

Still a package, not a module:

```
src/eval_harness/scorers/test_generation/
├── __init__.py          # registrations + shared evidence reader
├── execution.py         # test_executability, testgen_green_on_correct
└── mutation.py          # testgen_mutation_score, requirement_obligation_recall
```

`architecture.yaml` maps `scorers: [eval_harness.scorers]` by longest-prefix match, so a subpackage
resolves to the existing component and adds no import edge. Re-run the drift guard anyway; the
manifest is a protected path precisely so that assumption gets checked rather than assumed.

## Corpus

`corpora/testgen/v1/` — a new top-level directory, deliberately **not** under `flow-corpus/`.

`flow-corpus` is a package whose README declares it "fully synthetic and firewalled from any live
outcome data", whose data convention is `flow-corpus/data/suites/*.jsonl`, and which F-011 airgaps
from the harness with `flow_protocol` as "the ONLY shared surface". Putting a harness-loaded corpus
inside it muddies all three. `examples/datasets/sample.jsonl` is the existing precedent for
harness-loadable data outside a package; `corpora/` is that idea with a version directory and a
manifest.

`check_charter_invariants._MISSION_DIRS` is a presence check over seven paths, not an allowlist, so
a new top-level directory raises no charter finding. Confirmed, not assumed.

Corpus shape per item: a focal method, a known-correct reference implementation, a seeded mutant
set with equivalence marks, and a gold obligation set. Generated from control-flow templates with
p-use/c-use placeholders, stratified for reporting across control-flow categories. Frozen with a
manifest carrying `schema_version`, a generator seed, and per-item hashes.

## Gate configuration

```yaml
run:
  repetitions: 5
gate:
  rules:
    - score: test_executability
      metric: pass_power_k
      min: 0.90
      report_only: true
    - score: testgen_mutation_score
      metric: mean
      min: 0.60
      report_only: true
    - score: testgen_green_on_correct
      metric: mean
      max: 0.05
      report_only: true
    - score: requirement_obligation_recall
      metric: mean
      min: 0.70
      report_only: true
```

Every rule is advisory, so no uncalibrated number blocks anything. The bounds above are **soak
starting points recorded in a config file**, not spec thresholds — `openspec/project.md` requires
tunables to live on config rather than at call sites, and none of these four numbers appears in the
spec delta. They exist to be moved by evidence.

`pass_power_k` rather than `pass_at_k` on executability: the operational question is whether the
suite runs *every* time, not whether it ran once. The metric is `pass^k`, which the literature calls
"pass hat k" (τ-bench, 2024); this repository's `pass_power_k` is a house spelling of the same
thing, noted here so a reader does not go looking for a different metric.

## What was cut, and why

| Source-plan scorer | Disposition |
|---|---|
| `testgen_flake_rate` | Not a scorer. `repetitions: 5` + `pass_power_k` on `test_executability` (F-056) |
| `testgen_coverage_delta` | Deferred — needs a second instrumented run per item; own change |
| `testgen_traceability`, `testgen_revision_rate`, `test_duplicate_rate` | Deferred — no oracle in this corpus yet |
| `boundary_partition_coverage`, `negative_path_coverage` | Deferred — subsumed by obligation recall until the corpus declares partitions |
| `unsupported_assumption` | Deferred — judge-backed, so blocked behind calibration |
| `mutation_detection` | Redundant with `testgen_mutation_score` |
| `test_case_precision` | Deferred — needs a gold *negative* set the corpus does not yet carry |

Four scorers, twenty matrix cells, one corpus, one target. Everything above is real work and none
of it is lost — it is queued behind evidence that the first four are worth trusting.

## Compiles down to

A numbered ADR at land (next free is 0043 if `add-gate-decision-provenance` takes 0042), recording
the target-executes/scorers-read seam and the synthetic-corpus decision. F-numbers are claimed at
land.

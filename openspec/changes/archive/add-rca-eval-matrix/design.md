# Design: add-rca-eval-matrix

## Data model: triplet shape, ranked scoring

The source plan framed this as a choice between two benchmarks' conventions. It is not a choice —
they operate at different layers, and taking one from each is what makes the capability work:

- **Shape** from the triplet convention: onset instant, component from a finite set, reason from a
  finite set. This is what turns diagnosis into deterministic comparison instead of text similarity.
- **Scoring** from ranked accuracy: AC@1, AC@3, AC@5 over a ranked candidate list. Exact-match-only
  scoring throws away the operationally useful case where the right answer is second.

The `reason` field is deliberately **not scored in this change**. It is free text, so scoring it
needs a calibrated judge, which puts it behind `extend-judge-calibration`. Component and onset are
decidable now.

### Strict versus partial, and why it must be stated

The reference harness scores each triplet element independently and reports **two** numbers —
a strict accuracy (count of items scoring 1.0) and a partial accuracy (mean of fractional scores) —
with partial running roughly 1.5–2× strict. Published comparisons that omit which mode they used
are not comparable to each other.

This capability reports **strict by default and partial alongside it, both labelled**. No aggregate
in this change may present an unlabelled "accuracy". That is a spec requirement, not a convention,
because the failure mode is silent.

## Corpus

`corpora/rca/v1/`, generated. Each item:

```json
{"instance_id": "rca-0007",
 "timezone": "UTC+08:00",
 "candidates": ["svc-a", "svc-b", "db-01", "cache-2"],
 "correct": ["db-01"],
 "onset": "2026-03-04T11:42:00+08:00",
 "telemetry": {"metrics": {...}, "events": [...]},
 "difficulty": 0.34, "noise": 0.1}
```

`candidates` / `correct` deliberately mirror `solution_space` / `correct` in
`flow-corpus/data/suites/sdlc.jsonl`, which already carries 200 rows of exactly this shape. That is
not a coincidence to exploit quietly — it means the ranked scorers can be developed and
matrix-covered against an existing suite before the telemetry-bearing corpus exists, which takes the
longest-lead item off the critical path.

`timezone` is mandatory per the spec. The benchmark family this imitates records everything in
UTC+8 and names timezone drift as its own leading cause of spurious mismatches; an independent
replication attributes 23.3% of its "Timestamp Error" pitfalls largely to it.

Negative controls: items with no correct candidate, and items with several. Neither is
distinguishable from an ordinary item by any field the target can see.

## The `max-|Z|` baseline is a target, not a scorer

Worth stating explicitly because the obvious reading is wrong. "Pick the metric with the largest
absolute z-score and map it to a service" **produces a diagnosis**. Anything that produces a
diagnosis is a `TargetRunner`, not a `Scorer` — a scorer consumes one and grades it.

So the baseline registers as a deterministic target and is scored by the same five scorers as any
agent. That is the point: it is not a special-cased number printed next to the results, it is a
competitor evaluated on the identical path.

It also owes a target-kind matrix row (floor M1, M2, M3, M6 — `_matrix_coverage.py`), not a
scorer row.

## Scorers

| Scorer | Reads | Deterministic |
|---|---|---|
| `rca_ac_at_k` | ranked candidate list vs `correct` | yes |
| `rca_component_match` | top-1 component vs `correct` | yes |
| `rca_onset_within_tolerance` | claimed onset vs `onset`, timezone-normalised | yes |
| `rca_abstention_correctness` | declined-or-named vs whether the item is answerable | yes |
| `rca_false_accusation_rate` | named cause on an unanswerable item | yes |

No judge. `require_calibration_for_judge_gating` is never engaged, so this change does not queue
behind calibration.

Five scorers × the scorer floor (M1, M2, M3, M5, M6) = **25 cells**. Cells, not methods: a class
declaring `MATRIX_COMPONENTS` applies its dim set to every listed component
(`tests/_matrix_coverage.py:645`), so one parametrized method covers a whole column — the pattern
`TestTrajectoryScorersShared` already uses for seven trajectory scorers in eight methods. Matrix
classes must not inherit (`:609-618`).

File layout: `src/eval_harness/scorers/rca/{__init__,ranking,abstention}.py`. Five scorers fit
inside `MAX_FILE_LINES = 500` comfortably; a package keeps the ranking and abstention families
separable as the second wave lands.

## Gate configuration

```yaml
gate:
  rules:
    - score: rca_ac_at_k
      metric: mean
      min: 0.30
      report_only: true
    - score: rca_abstention_correctness
      metric: mean
      min: 0.80
      report_only: true
    - score: rca_false_accusation_rate
      metric: mean
      max: 0.20
      report_only: true
```

Advisory only. The 0.30 is not aspirational modesty — the best independent full-benchmark result
reported for this task family is 12.5% strict / 22.4% partial. A starting bound in that region is
what honest looks like, and it lives in config so our own evidence can move it. It is explicitly
**not** derived from any published number: the corpus is ours, so the bound has to come from the
baseline's measured performance on it (task 6.2), not from a leaderboard.

## What was cut, and why

| Source-plan scorer | Disposition |
|---|---|
| `counterfactual_support` | Infeasible on recorded telemetry, and structurally cannot be a `Scorer`. See below |
| `rca_mrr` | Attributed to RCAEval, which does not define it |
| `rca_avg_at_k` | Deferred — real, defined by RCAEval, but AC@k at three cut-offs already answers the question |
| `rca_reason_match`, `rca_triplet_all` | Deferred behind judge calibration (free-text `reason`) |
| `rca_timeline_completeness`, `rca_citation_grounding`, `rca_capa_actionability` | Deferred — need real telemetry, which is out of scope per `proposal.md` |

### Why `counterfactual_support` is cut, in full

It was the source synthesis's headline unique discovery, so it deserves more than a table row.

**It is not novel.** AID (Fariha, Nath & Meliou, SIGMOD 2020) formalises interventional debugging
with fault injection; Sage (Gan et al., ASPLOS 2021) states the SRE practice directly — "SREs can
verify if a suspected root cause is correct by reverting a microservice's configuration to a state
known to be safe." The genuinely under-cited part is the A-B-A *restore-and-confirm-return* step,
which appears as reasoning but not as a named validation protocol.

**It is not feasible on this corpus.** Recorded telemetry is an immutable snapshot; there is no
world to replay with the cause absent. Sage's own workaround on historical data is model-based
counterfactual estimation — a causal Bayesian network plus a CVAE per service — which needs a
correct dependency graph, causal sufficiency, stationarity and enough samples. On this benchmark
family, Granger, PC, FCI, LiNGAM and NTLR all score **0.00 at Acc@1 and Acc@10**, because roughly 30
timestamps per window are being fitted against 640–2500 metric columns.

**And it cannot be a `Scorer` regardless.** A scorer receives one `(item, output)` pair and is
handed a fresh `RunContext` per attempt (`src/eval_harness/core/_execution_strategies.py:281-282`), with `extra`
defaulting to a new dict and the item RNG re-derived — so it cannot detect repetition, let alone
re-execute under a modified configuration. Counterfactual replay needs re-configuration, for which
no seam exists anywhere.

**The well-posed substitute**, if the real-incident corpus is ever unblocked, is the fault-injection
record: knowing the intervention turns an ill-posed inverse problem into a forward verification
task. That is a corpus property, not a scorer.

## Compiles down to

A numbered ADR at land recording the shape-from-triplet / scoring-from-ranked-accuracy split, the
mandatory-timezone decision, the baseline-as-target decision, and the counterfactual cut.

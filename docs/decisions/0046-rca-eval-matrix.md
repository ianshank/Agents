# 0046 — RCA evaluation matrix: triplet shape, ranked scoring, baseline-as-target

- Status: **Accepted.**
- Date: 2026-09-06
- Related: `openspec/changes/add-rca-eval-matrix/` (design, tasks, review),
  ADR 0031 (scorer conventions), ADR 0032 (matrix obligations), ADR 0039
  (allowlisting), F-067. Builds on the ranking-scorer prototype (PR #190).

## Context

Root-cause diagnosis benchmarks conflate two layers: the *shape* of an answer
(onset instant, component from a finite set, reason from a finite set — the triplet
convention) and the *scoring* of it (ranked accuracy at several cut-offs). The source
plan framed them as a choice; they operate at different layers, and taking one from
each is what makes the capability decidable without a judge.

Three further pressures shaped this change:

1. The reference benchmark family records everything in UTC+8 and names timezone drift
   as a leading cause of spurious mismatches; an independent replication attributes a
   23.3% "Timestamp Error" pitfall rate largely to it.
2. The dominant real-world failure mode is confident diagnosis on incomplete evidence
   ("Hallucination in Interpretation" at 71.2% in one replication over 1,675 runs), so
   a benchmark that cannot distinguish "I don't know" from a wrong guess cannot measure
   the thing that goes wrong.
3. A 2026 audit across three benchmark families found untuned statistical baselines
   competitive with published RCA methods — an imported leaderboard number cannot show
   whether a corpus is separable; only a baseline run on *that* corpus can.

## Decision

1. **Shape from the triplet convention; scoring from ranked accuracy.** Each item
   declares a finite candidate set, confirmed cause(s) (possibly empty, possibly
   several), an onset instant, and a mandatory timezone. `rca_ac_at_k` reports strict
   and partial figures at k ∈ {1, 3, 5}, each labelled with its k; no aggregate may
   present an unlabelled "accuracy".
2. **Timezone is mandatory and comparison is offset-explicit.** A corpus item with
   timestamps and no declared timezone is rejected at load; a claimed onset without an
   offset is refused (never interpreted in an implicit local zone); both instants are
   normalised to UTC in the evidence so a shifted answer is visibly wrong.
3. **The `max-|Z|` baseline is a target, not a scorer.** Anything that produces a
   diagnosis is a `TargetRunner`. The baseline (`rca_maxz`) ranks candidates by the
   largest absolute z-score across the onset boundary and abstains below `z_floor`,
   so the abstention scorers grade it on the identical path as any agent.
4. **Corpus difficulty is a gated measurement, not a claim.** The generator calibrates
   the synthetic telemetry against the baseline before freezing; the manifest records
   the measured per-cell strict AC@1 (`baseline_strict_ac1`), and
   `gen_rca_corpus.py --check` fails when a regeneration leaves the calibrated bands
   (`BASELINE_BANDS`). The first calibration pass caught a real defect: a cause
   spiking all three metrics won every ranking by construction, so faults now move
   one or two metrics, never all three.
5. **`counterfactual_support` is cut.** It is not novel (AID, SIGMOD 2020; Sage,
   ASPLOS 2021), not feasible on recorded telemetry (an immutable snapshot has no
   world to replay), and structurally cannot be a `Scorer` (a scorer receives one
   `(item, output)` pair and cannot re-execute under a modified configuration). The
   well-posed substitute — a fault-injection record — is a corpus property, deferred
   with the real-incident corpus (CHARTER §4 invariant 7).
6. **Every gate rule is advisory** (`report_only`, F-062). Bounds are soak starting
   points in `config/rca_eval.yaml`; a blocking threshold is a later, separate change
   stating its soak evidence.

## Consequences

- `corpora/rca/v1/` ships 96 generated items (4 answerability classes × 3 difficulty
  strata × 8), shape-identical negative controls, and a keyed holdout split
  (the `flow_corpus.partition` idiom reused as an idiom — the F-011 airgap holds).
- Five scorers × the scorer floor (M1/M2/M3/M5/M6) = 25 matrix cells, plus the
  target row (M1/M2/M3/M6) and an M8 pipeline asserting ledger invocation of the
  target and every scorer.
- `rca_reason_match` and any free-text reason scoring stay deferred behind judge
  calibration (F-057/F-066); this change engages no judge.
- `public_surface_baseline.json` is unchanged: the scorers subpackage declares no
  `__all__` (the state.py / trajectory.py precedent).

## Alternatives considered

- **Score the `reason` field now:** rejected — free text needs a calibrated judge,
  which queues behind F-057/F-066 for no v1 gain.
- **MRR alongside AC@k:** rejected — attributed to RCAEval, which does not define it
  (its §4.2 supports AC@k and Avg@k only).
- **A corpus of real internal incidents:** rejected — host-specific telemetry is
  committed source from internal systems, a CHARTER §4 invariant 7 matter requiring
  a §3 Ratified Amendment; the synthetic corpus is the Charter-safe scope.

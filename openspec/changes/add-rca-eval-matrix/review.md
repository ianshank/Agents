# Review: add-rca-eval-matrix

**Reviewed:** the externally supplied `add-rca-eval-matrix` package, re-verified against `28eb09d`,
with its external citations independently re-fetched. Full findings:
`docs/plans/scenario-eval-matrices/REVIEW.md` §A16 and §C1.

## Verdict

The source package had the best instincts of the four — deterministic component and onset fields,
judge only on free text, abstention as a first-class metric — and the worst evidence base. Its
headline progress claim does not survive replication, one of its metrics is attributed to a paper
that does not define it, and its "strongest possible oracle" cannot run on the corpus it specifies.

The scope was also blocked in a way the source did not notice, and the fix is a split rather than a
wait.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| A16 | Real replayed incident bundles proposed with no governance note | Split out and declared out of scope. The governing clause is CHARTER §4 **invariant 7** — "Nothing host-specific is committed" — not §3. Synthetic scope proceeds now |
| C1.10 | `rca_mrr` attributed to RCAEval | RCAEval §4.2 defines **AC@k and Avg@k only**. Cut |
| C1.e / A9 | `counterfactual_support` as "the strongest oracle available" | Not novel (AID 2020, Sage 2021), not feasible on recorded telemetry, and structurally cannot be a `Scorer`. Cut, with the reasoning kept in `design.md` |
| C1.a | "OpenRCA agents went ~10% → ~33%" | Best independent full-benchmark replication is 12.5% strict / 22.4% partial. The ~34.9% figure is a vendor self-report. Removed; the honest numbers are in `proposal.md` |
| C1.a | No strict-vs-partial discipline | The reference harness emits both, partial ~1.5–2× strict. Both are now required, both labelled (task 4.2) |
| C1.a | Onset tolerance with no timezone | The benchmark family is UTC+8 throughout and names timezone drift as its own leading mismatch cause. Declared timezone is now mandatory and load-rejected if absent |
| A13 | ±60s, k=5 in requirement prose | No numeric threshold in the spec delta. Tolerance and bounds are config fields |
| A7 | Matrix rows as one checkbox | 25 cells enumerated, with the parametrization mechanics stated so the cost is neither hidden nor inflated |
| A6 | No advisory gating | Depends on `add-gate-decision-provenance` |
| A17 | No ordering against `prove-m8-execution` | Declared as a dependency |

## Findings raised by this change

**R1 — a trivial baseline must ship, but not for the reason first given. Retracted and rebuilt.**

Round 1 of the parent review, and the first draft of this package, claimed that an untuned
largest-|z| predictor scores 0.365 pooled against 0.246 for a published RCA method, and that this
"beats" the ~33% agent figure the source plan wanted to celebrate. **The two numbers are not
comparable, and the second pass caught it.** Three independent reasons:

- **Different case pool.** The 778 scoring units span 11 subsystems across *three* benchmark
  families. The reference benchmark is a minority slice of it; 778 is not its 335.
- **Different scoring.** The audit states verbatim that it retains each benchmark's native scale —
  fractional partial credit for one family, strict {0,1} for the others, deliberately un-binarised.
  So the pooled figure carries partial credit, which is nearer the 22.4% "partial" number than the
  12.5% "strict" one.
- **Different task.** The baseline predicts a *service identifier*. Strict accuracy on the reference
  benchmark requires component **and** onset **and** reason simultaneously.

Worse, quoting the pooled figure as a ranking is the exact misreading the audit was written to
attack: all six pairwise comparisons reverse sign across subsystems, every 95% prediction interval
crosses zero, leave-one-system-out selection picks the worse method on up to 5 of 11 subsystems,
and the published method actually *beats* the baseline on three of them.

**What survives is the design decision, on better grounds.** The audit's real finding — untuned
statistical baselines are competitive with published methods, and pooled numbers do not license
recommendations — argues for measuring our own floor on our own corpus rather than importing anyone's
number. So the baseline ships as a first-class target, evaluated by the identical scorers on the
identical items, and no agent result is reported without it. That remains the single most
credibility-preserving decision in the package. The justification is now something this repository
can verify rather than something it has to cite.

**R2 — no pooled claim, ever, from this corpus.** Following directly from R1: any per-domain or
per-difficulty claim needs per-domain evidence. A single averaged accuracy over a corpus spanning
difficulty strata is exactly the artifact the audit shows to be unreliable, and this capability
will generate one by default unless the reporting is designed against it.

**R3 — the corpus can be prototyped against something that already exists.** `sdlc.jsonl` carries
200 rows of `solution_space` / `correct` — the AC@k data model in miniature. Task 1.1 builds the
ranking scorers against it before the telemetry corpus exists, which removes the longest-lead item
from the critical path. Read as a fixture copy, not by reaching into `flow-corpus/` at run time:
F-011 makes `flow_protocol` the only shared surface, and reusing a *shape* must not become a
dependency.

**R4 — the RCAEval citation needs downgrading generally, not just for MRR.** It is a four-page
WWW '25 Companion short paper whose preliminary experiments cover one system of one dataset with 8
of 15 baselines, and it contains **no LLM evaluation at all**. Fine as a source for a metric
definition; wrong as the methodological precedent for an LLM-agent eval harness.

**R5 — the vendor MTTR range should not appear anywhere downstream.** No peer-reviewed or
independently audited source supports 30–70% MTTR / 40–60% MTTD / 60–90% alert reduction, and one
URL in the source list does not resolve. The one methodologically serious study — a full year,
thousands of incidents, a control group, committee-reviewed timestamps — reports **20%** average MTTR
improvement, is first-party, is a preprint, and is **not about AI**: its own lesson heading reads
"Do not over-index on AI based systems for diagnosis." If an MTTR anchor is needed, that is the
honest one, and it reframes the pitch.

**R6 — the better headline than any solve rate.** The 1,675-run replication publishes a failure
taxonomy: Hallucination in Interpretation **71.2%**, Incomplete Exploration **63.9%**, both above
66%/53% for *every* model regardless of capability tier, and unmoved by prompt engineering. The
bottleneck is the agent framework, not the model — which is a far stronger argument for building
this harness than a percentage, and it is what motivates `rca_abstention_correctness` and
`rca_false_accusation_rate` as the two scorers to lead with.

## Correction to round 1 of the parent review (2026-09-05)

Round 1 §A16 asserted these corpora were blocked on a "CHARTER §6 Ratified Amendment". Two errors:

1. **Wrong section.** "Ratified Amendments" is a subsection of **§3** (`docs/CHARTER.md:86`;
   §4 begins at :115). §6 is the escalation clause — "surface it for human decision" — not the
   register. Every other reference in the tree says §3; round 1 quoted the one inconsistent line in
   the flywheel proposal and promoted it to a headline.
2. **Wrong ground.** §3's own Included list names "datasets" in scope, and every §3 exclusion
   regulates a *behaviour* rather than data provenance. The flywheel was blocked for a *pipeline* —
   "ingestion, redaction, deduplication and review-queue" — and its non-goal is *unredacted*
   production data, which concedes that redacted committed data is not per se the bar.

The correct objection is **CHARTER §4 invariant 7**: "Nothing host-specific is committed." Replayed
incident telemetry is host-specific by construction. That is an invariant relaxation escalated under
§6 and registered under §3 — a different route with a different remedy (deterministic redaction
gating corpus entry).

The disposition is unchanged: start synthetic. The reasoning had to be rebuilt.

## Open questions for the reviewer

1. `rca_avg_at_k` is cut for scope, not for evidence — RCAEval does define it. Worth adding in the
   second wave if AC@k at three cut-offs proves too coarse.
2. Synthetic telemetry good enough to make `max-|Z|` non-trivial is harder to generate than the
   ranking corpus. If the generator produces telemetry the baseline solves at 90%, the corpus is too
   easy and the baseline stops being informative. Settle the difficulty calibration before 2.4
   freezes.

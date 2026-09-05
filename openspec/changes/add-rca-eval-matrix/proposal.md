# Change: add-rca-eval-matrix

**Status:** proposed *(synthetic scope only — the real-incident corpus is explicitly out of scope
and blocked; see "What is deliberately not here")*
**Date:** 2026-09-05 · **Author track:** `claude/` agent lane
**Motivated by:** `docs/plans/scenario-eval-matrices/REVIEW.md` §A16, §C1
**Depends on:** `add-gate-decision-provenance`, `prove-m8-execution`
**Compiles down to:** `docs/plans/scenario-eval-matrices/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

Root-cause diagnosis is a ranking problem over a finite candidate set, and the harness has no way to
score one. It has trajectory scorers (F-051) and a `mock_http` state adapter (F-060) that were built
for exactly this shape of task, and nothing scenario-specific to point them at.

The published evidence also says something uncomfortable that this change is designed to surface
rather than hide. On the reference benchmark, agents solve roughly one case in eight: the original
best baseline is 11.34% strict, and an independent process-level study that re-ran all 335 cases
across five models (1,675 runs) reports a best of 12.5% strict / 22.4% partial. Whatever this
capability measures, it will not be measuring a solved problem.

Separately — and this is the design consequence — a 2026 audit over 778 matched scoring units
finds that **untuned statistical baselines are competitive with published RCA methods**, that all
six method pairs it compares reverse sign across subsystems, and that every random-effects
prediction interval crosses zero. Its thesis is that pooled leaderboard numbers do not license
recommendations.

The response is not to quote its headline number back (see `review.md` R1 — the pooled figure is
not comparable to a strict single-benchmark accuracy, and this proposal originally misused it). The
response is structural: **ship a trivial baseline as a first-class target and evaluate it on the
same corpus with the same scorers, every time.** If an agent cannot beat argmax-of-z-score on our
own data, that is a fact about our data we need to know before anyone sees a slide.

## What changes

- A **synthetic incident corpus** in the existing `solution_space` / `correct` shape, with a finite
  candidate-cause set per item, a confirmed cause, and negative controls.
- A **deterministic `max-|Z|` baseline target** — the honest floor every agent must clear.
- Five scorers, all deterministic, no judge:
  `rca_ac_at_k`, `rca_component_match`, `rca_onset_within_tolerance`,
  `rca_abstention_correctness`, `rca_false_accusation_rate`.
- Matrix rows for all five, and the regenerated coverage artifact.
- Advisory gate rules only.

## Why the corpus starts synthetic, and where it starts

`flow-corpus/data/suites/sdlc.jsonl` already carries 200 rows in exactly the shape this capability
needs:

```json
{"instance_id":"sdlc-0000","domain":"sdlc","difficulty":0.0,
 "solution_space":["cand_0_0","cand_0_1","cand_0_2","cand_0_3"],
 "correct":["cand_0_0"],"tool_available":true,"noise":0.0}
```

`solution_space` is the finite candidate set; `correct` is the confirmed answer; `difficulty` and
`noise` are already parameterised. That is the AC@k data model in miniature, and it means the
ranked-diagnosis scorers can be built, matrix-covered and soaked **before** a single real incident
is curated — which removes the longest-lead item from the critical path.

The corpus this change ships is a telemetry-bearing extension of that shape at `corpora/rca/v1/`,
generated rather than replayed. It is not placed under `flow-corpus/` for the reasons in
`add-testgen-eval-matrix/design.md`: that package is airgapped from the harness by F-011 with
`flow_protocol` as the only shared surface, and its data convention is `data/suites/`.

## What is deliberately not here

**The real-incident corpus is out of scope and is blocked.** The source plan proposed 30–40
replayed internal incident bundles of logs, metrics, traces and deploy events, plus timeline
completeness, citation grounding against real telemetry artifacts, and CAPA actionability scoring.

The governing clause is **CHARTER §4 invariant 7**, and it is worth quoting exactly because a
looser reading of §3 does not actually forbid this:

> **No secrets, no machine fingerprints in the repo.** Credentials come from environment variables
> only… **Nothing host-specific is committed.**

Replayed internal incident bundles — logs, metrics, traces, deploy events — are host-specific by
construction. Hostnames, service identifiers, internal IPs and deploy identifiers are the *signal*;
strip them and there is nothing left to diagnose. That is an invariant relaxation, escalated under
CHARTER §6 ("surface it for human decision") and registered as a §3 Ratified Amendment, and it needs
deterministic redaction gating corpus entry — the design
`add-production-eval-flywheel/design.md` already sketches.

CHARTER §3 itself is the weaker argument and should not be leaned on: it lists "datasets" in scope,
and every §3 exclusion regulates a *behaviour* — training, live evals in gates, auto-merge,
permissive parsing — not data provenance. A static committed corpus is not "a general observability
platform"; the blocked flywheel was blocked for building an *ingestion, redaction, deduplication and
review-queue pipeline*, which is a different thing. The invariant-7 objection survives that
distinction; the §3 objection does not.

Note also **F-036** ("Real-transcript corpus bridge — flow_corpus ingestion from labeled store
records"), `status: deferred` in `features.yaml`, superseded by the blocked flywheel. Real records
entering a corpus is parked, not forbidden — which is precisely why it needs a decision rather than
an assumption in either direction.

Nothing in the synthetic scope touches invariant 7. Splitting the two is what lets the scorers ship
now instead of waiting on a governance decision that has been open since August.

Also cut, on evidence rather than scope:

- **`counterfactual_support`** — replaying an incident with the alleged cause removed requires
  re-executing a system, which recorded telemetry cannot support, and a `Scorer` cannot re-execute
  anything anyway (`src/eval_harness/core/interfaces.py:39-49`). Prior art exists (AID, SIGMOD 2020; Sage, ASPLOS
  2021) and is *live*; Sage's own workaround on historical data is model-based counterfactual
  estimation, whose causal machinery scores 0.00 at Acc@1 and Acc@10 on this benchmark family. The
  well-posed substitute is the fault-injection record, not a replay.
- **`rca_mrr`** — attributed to RCAEval, which does not define it. RCAEval §4.2: "We currently
  support two standard metrics: AC@k and Avg@k."
- **`rca_triplet_all`, `rca_reason_match`, `rca_timeline_completeness`, `rca_citation_grounding`,
  `rca_capa_actionability`** — deferred. The last three need real telemetry; the free-text `reason`
  field needs a calibrated judge.

## Impact

- **Protected paths:** `src/eval_harness/scorers/**`, `config/**`, `features.yaml`,
  `scripts/validations/**`, root `tests/**`.
- Root `eval_harness` coverage floor **96%**.
- New matrix obligation: 5 scorers × the 5-dimension scorer floor = **25 cells**, plus one target
  row. These land in this change (ADR 0032).
- Both surface baselines regenerated; both README registry tables updated.

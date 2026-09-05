# Implementation Plan — Scenario Eval Matrices and the VP Presentation

**ID:** PLAN-2026-09-05-scenario-eval-matrices
**Date:** 2026-09-05 · **Base commit:** `a8a7d93`
**Motivated by:** [`./REVIEW.md`](./REVIEW.md) — a two-pass peer review of an externally supplied
four-package plan. Pass 2 ran the same method against pass 1 and retracted five of its own findings.
**Scope:** sequence the work from where the tree actually is to a VP presentation that survives a
hostile question, and say plainly which deck can be given on which date.
**Non-goals:** the presentation deck itself (this plans it, does not write it); benchmark adapters;
live evaluation in merge CI.

This document is the compile-down target the four change packages name in their
`Compiles down to:` headers.

---

## The uncomfortable part, first

**The deck the source plan was aiming at cannot be given.** It promised agent performance across
test generation, RCA and requirements generation. As of `a8a7d93`:

| Claimed deliverable | Actual state |
|---|---|
| 35 scenario scorers | **0 implemented.** 13 are proposed across three change packages |
| Three curated corpora | **0 exist** |
| `pass^k` reliability over scenario runs | machinery ships (F-056); nothing scenario-specific to aggregate |
| Judge-calibration numbers (κ, ECE, Brier, AUROC) | **nothing to compute over** — see the blocker below |

And one number that has to be said out loud before anyone builds a slide on it:
`openspec/changes/add-measurement-harness-wedge/proposal.md` records that the live outcome store
held **zero `HUMAN_AUDIT` labels across 46 records**, with all 8 agent-domain rows unlabelled. Only
`HUMAN_AUDIT` labels feed `tau`/health (ADR 0005 §3-4). Until someone labels, every
calibration-derived figure is an empty query, not a low score. *(Recorded 2026-08-05; re-check the
store before quoting it either way.)*

So the question is not "which numbers do we show" — it is **"which deck is honestly available on
which date."** Three are, and they are very different.

---

## Three decks, and which one to give

### Deck A — "The measurement system" · **available today**

Subject: *we built an evaluation system whose numbers cannot be quietly weakened, and here is the
proof.* Every claim below is verifiable against this commit.

| Claim | Evidence |
|---|---|
| 63 declared capabilities, each with an executable proof, 61 run per-PR | `features.yaml`; `scripts/validate.py --tier fast` → 61/61 |
| 41 registered components with a derived coverage matrix, freshness-gated | `docs/matrix-coverage.md`; `tests/test_matrix_coverage.py` |
| Composability credit requires **observed execution**, not a name in a config | `tests/_m8_probe.py`; F-063 |
| Eval-defining files cannot change without a labelled, CODEOWNER-reviewed PR | `scripts/eval_protected_paths.py`; F-007 |
| A gate's verdict reaches every exported artifact | F-062 — live in `out/demo/report.html` |
| One command, fully offline, deterministic, end to end | `./demo/run_demo.sh` — verified at this commit, exit 0, 6 reports |

### Deck B — "First scenario results" · **~1 sprint**

Subject: *here is how our agents actually do at generating tests, measured against seeded faults.*
Needs `add-testgen-eval-matrix` implemented and soaked. Four scorers, a generated corpus, no judge —
so it does not queue behind calibration.

### Deck C — "The three-scenario picture" · **~3 sprints, plus a governance decision**

Adds RCA and requirements. Gated on the CHARTER §4 invariant-7 decision (below) and on labelling
capacity for judge-gated metrics.

### Recommendation: give **Deck A** now, and pre-sell Deck B

Not as a fallback. Two reasons:

1. **Scenario numbers without a trusted measurement system are worth nothing.** The first question a
   sharp VP asks about any agent metric is "how do I know that number is real." Deck A *is* that
   answer. Give it first and Deck B lands on prepared ground; give Deck B first and you will be
   answering Deck A's content from the back foot, without slides.
2. **The measurement system is the harder artifact and the more durable one.** Scorers are weeks;
   the governance that makes their output trustworthy took this repository sixty-three features.

---

## Deck A, slide by slide

Ten slides. Every one has an evidence line; anything without one is cut.

| # | Slide | Evidence | Note |
|---|---|---|---|
| 1 | The problem: an agent metric nobody can audit is a liability, not an asset | — | 60 seconds, no numbers |
| 2 | **Three times our own gates were wrong, and how we caught them** | see below | **Lead with this** |
| 3 | What the system enforces: 63 capabilities, 61 executable proofs per PR | `validate.py --tier fast` | Run it live if the room is technical |
| 4 | Derived coverage, not a hand-maintained list: 41 components × 6 dimensions | `docs/matrix-coverage.md` | A rowless component fails CI (ADR 0032) |
| 5 | Composability now requires observed execution | F-063, `tests/_m8_probe.py` | The M8 story, slide 2's third instance |
| 6 | The gate's verdict is in the artifact, not just the CI log | F-062, `out/demo/report-fail.html` | Show the actual FAIL table |
| 7 | **Live demo** — one command, offline, deterministic | `./demo/run_demo.sh` | See rehearsal checklist |
| 8 | Weakening a metric requires a labelled, reviewed PR | F-007, CODEOWNERS | This PR series is itself the worked example |
| 9 | What we have *not* measured yet, and why | the honesty slide, below | Do not skip this |
| 10 | The ask | three asks, below | Specific, not "support" |

### Slide 2 — the three instances

This is the strongest slide in the deck, and it is the one nobody else can copy, because it requires
having been wrong in public and caught it.

1. **F-049** — a calibrated-gate health floor scanned only bins above raw confidence 0.5 and
   accumulated into a `0.0` initialiser, so a domain whose audits all sat below that line reported a
   *passing* CI width having measured nothing. Fail-open, reproducible, closed.
2. **`prove-m8-execution`** — the composability dimension credited a component the instant its name
   appeared in a validated config. One credited cell was **provably invoked zero times**. Now an
   execution ledger patches the registry's single construction choke point, and a pipeline that
   declares a component it never calls fails.
3. **This cycle, twice.** The quality gate's decision reached no artifact — sinks fired before the
   gate was evaluated (F-062). And the two network-backed judges built real SDK clients in their
   constructors, so an offline matrix cell would have **attempted real network egress from CI and
   still reported green**, because the engine converts a scorer exception into a `0.0` score rather
   than raising (F-063).

Optional fourth beat, if the room is senior enough to value it: **the review that produced this plan
retracted five of its own findings**, three of them in headline sentences, after a second adversarial
pass. That is the behaviour you want in a measurement system and in the people running it.

### Slide 9 — the honesty slide

Say these before you are asked:

- **No agent performance numbers yet.** Zero scenario scorers implemented. Deck B is where those live.
- **No calibration numbers.** Zero `HUMAN_AUDIT` labels in the store; the report has nothing to
  compute over. This is a labelling-capacity problem, not a technical one.
- **Expect a low ceiling on RCA.** Best published result on the reference benchmark is **12.5%
  strict / 22.4% partial**. Have that conversation before building, not after the first result.
- **Three standing risks:** proxy-metric validity; judge self-gaming; and gate-mechanism integrity —
  the risk that a gate looks green while measuring nothing. Slide 2 is the evidence we take the
  third seriously.

---

## Numbers that must not appear in any deck

Each was checked in [`REVIEW.md`](./REVIEW.md) Part C and failed. Listed so they cannot creep back
in from the source material.

| Do not say | Why | Say instead |
|---|---|---|
| "OpenRCA agents went 10% → 33%" | The 2026 anchor is a vendor self-report; independent replication reaches 12.5% strict | "best independent full-benchmark result is 12.5% strict / 22.4% partial" |
| "a trivial heuristic scores 36.5%, beating agents" | Different case pool, scoring scale and task — the comparison is invalid | "untuned statistical baselines are competitive; we measure our own floor on our own corpus" |
| "35.9% of Java PRs improve coverage" | Denominator is 64 *instrumented code-plus-tests* PRs, not 532 Java PRs | "of instrumented code-plus-tests PRs" |
| "industry sees 30–70% MTTR reduction" | No peer-reviewed or audited source; one cited URL does not resolve | Meta's DrP: **20%**, full year, control group — and **not an AI system** |
| "raw + normalized mutation score per Inozemtseva" | Only the *normalized* denominator is hers; the focal-method form is a 2026 adaptation | cite both papers, and keep "non-equivalent" in both denominators |
| any κ / ECE / Brier / AUROC figure | Nothing to compute over until labelling happens | "calibration is instrumented; the corpus is the next dependency" |
| "200 paired labels gives a κ CI width of 0.10" | Wrong by 4–6×; that is a ±0.10 **half**-width | "±0.10 half-width needs ~200–350; width 0.10 needs ~800–1,200" |

---

## Sprint plan

Every change below touches protected paths and needs the `eval-change-approved` label. That latency
is the schedule's dominant term, not the coding.

### Sprint 1 → unlocks Deck B

- Finish `prove-m8-execution` **task 4** (breadth to the 19 test-only components). Unblocks nothing
  else, but leaves the matrix honest before 13 scorers arrive.
  **Correction (2026-09-05): this was called "Small" here and it is not.** The 19 cells need
  `PIPELINES` converted from literal dicts to zero-arg factories, which breaks five call sites,
  two of them protected validation scripts. Sized in
  [`plans/eval-delivery-sequencing/PLAN.md`](../eval-delivery-sequencing/PLAN.md) WS-2, which also
  discharges the change's stated AST precondition. Treat it as the sprint's dominant engineering
  item, not a warm-up.
- Implement `add-testgen-eval-matrix`: the corpus generator (control-flow templates, seeded
  non-equivalent mutants, gold obligations), the allowlisted execution target, four pure-reader
  scorers, 20 matrix cells, advisory gate rules only.
- Begin the soak. **The soak is the deliverable, not the scorers** — Deck B's numbers are a
  distribution over held-out items, not a single run.

### Sprint 2

- `add-rca-eval-matrix`, synthetic scope only. Prototype `rca_ac_at_k` against the existing
  `flow-corpus/data/suites/sdlc.jsonl` (200 rows already in `solution_space`/`correct` shape) before
  the telemetry corpus exists — this takes the longest-lead item off the critical path.
- Ship the `max-|Z|` baseline as a **target**, and report no agent result without it.

### Sprint 3

- `add-requirements-gen-eval-matrix`: revision-scoped provenance first, scorers second. Task 2.3
  (mutate a source, assert the check notices) is the one that proves provenance works.
- Judge-calibration corpus — the long pole. Nothing judge-gated activates without it.

---

## Blockers, owners unassigned

| # | Blocker | Consequence if unresolved |
|---|---|---|
| B1 | **CHARTER §4 invariant 7** — "nothing host-specific is committed". Real incident telemetry is host-specific by construction | RCA stays synthetic-only. Survivable, but decide it deliberately rather than by drift |
| B2 | **Zero `HUMAN_AUDIT` labels.** Someone must produce ~200–350 paired labels per judged scorer | Every judge-gated metric stays advisory forever; Deck C loses its calibration slide |
| B3 | **Protected-path review latency.** Every change needs a label plus CODEOWNER review under single-maintainer branch protection (ADR 0037) | A three-sprint plan is a hope, not a schedule |
| B4 | `prove-m8-execution` task 4 outstanding | 13 new scorers land on a partially-honest matrix |

---

## The ask — three items, all specific

A deck that ends in "support" gets support and no decisions. End on these:

1. **Decide B1.** Real incident telemetry, under a §3 Ratified Amendment with deterministic
   redaction — or synthetic-only, permanently. Either is workable; ambiguity is not.
2. **Fund B2.** Name who produces the paired labels and by when. Without it, "calibrated judge" is a
   capability we own and never switch on.
3. **Name a CODEOWNER turnaround target for B3.** Without one, the sprint plan above has no
   defensible dates.

---

## Rehearsal checklist

`demo/run_demo.sh` is the highest-value ninety seconds in Deck A and the easiest thing to fumble.

- [ ] Run it on the presenting machine, from a clean clone, **on the day**. It was verified at
      `a8a7d93` (exit 0, six reports) — that is not the same as verified on the laptop in the room.
- [ ] Have `out/demo/report-fail.html` open in a tab already. Slide 6 is a screenshot of it; the demo
      just proves the screenshot is real.
- [ ] Know the failing number cold: `helpfulness.mean=0.844` against `min 0.95`, exit 1. The point is
      that a real CI step stops there.
- [ ] Have `validate.py --tier fast` ready in a second terminal for slide 3 if the room is technical.
      Do not run it if they are not — 61 green lines is a wall of text to a non-engineer.
- [ ] Rehearse slide 9 out loud. Volunteering what you have not measured is the move that buys the
      rest of the deck; delivered hesitantly it reads as an apology instead.

---

## Related documents

- [`./REVIEW.md`](./REVIEW.md) — the two-pass peer review, including Part E's five retractions
- [`../../../openspec/changes/add-gate-decision-provenance/`](../../../openspec/changes/add-gate-decision-provenance/) — F-062, landed
- [`../../../openspec/changes/prove-m8-execution/`](../../../openspec/changes/prove-m8-execution/) — F-063, task 4 outstanding
- [`../../../openspec/changes/add-testgen-eval-matrix/`](../../../openspec/changes/add-testgen-eval-matrix/) — Sprint 1
- [`../../../openspec/changes/add-rca-eval-matrix/`](../../../openspec/changes/add-rca-eval-matrix/) — Sprint 2
- [`../../../openspec/changes/add-requirements-gen-eval-matrix/`](../../../openspec/changes/add-requirements-gen-eval-matrix/) — Sprint 3

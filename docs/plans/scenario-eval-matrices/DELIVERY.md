# Delivery Plan — getting the VP presentation into the room

**ID:** PLAN-2026-09-05-vp-delivery · **Revision 2**
**Date:** 2026-09-05 · **Base commit:** `655de2e` (merge of PR #183)
**Companion to:** [`./PLAN.md`](./PLAN.md), which decides *which deck*. This decides *how it gets
delivered*, and records what PR #183 changed underneath it.
**Non-goals:** writing the deck; re-litigating the deck choice (Deck A first still holds).

**Revision 2** is an adversarial pass by the same author against revision 1, a few hours later,
using the method [`./REVIEW.md`](./REVIEW.md) applied to the source plan: every falsifiable claim
re-checked by running something, with the command in the text. It found **five defects in revision
1**, one of them serious enough that it had already reached a pull-request description. They are in
§0 rather than quietly corrected, because a document whose subject is "numbers that look like
measurements and are not" does not get to fix its own silently.

---

## 0 · Findings against revision 1

### D1 · `n=300` was a 5× inflated denominator — **SEV-1, and it escaped this document**

Revision 1 reported the discrimination table as **n=300 per slice** and "1,200 measurements", and
those figures reached PR #186's description and a status message.

Measured:

```
repetitions: 5  →  60 item(s) × 5 = n=300   mean 1.000 / 1.000 / 0.000 / 1.000
repetitions: 1  →  n=60                     mean 1.000 / 1.000 / 0.000 / 1.000
```

**Identical.** The five repetitions add no information, and could not: the corpus supplies a fixed
`suite`, the target executes it deterministically, and ADR 0043 makes the scorers pure functions of
its evidence. `repetitions > 1` exists to measure *the target's* variance — and this target has none,
because there is no model in it. So n=300 is **60 distinct measurements with a 5× multiplier**.

This is precisely the defect [`./REVIEW.md`](./REVIEW.md) Part C caught in the source material —
"the denominator is 64 instrumented code-plus-tests PRs, not 532 Java PRs" — reproduced inside the
document warning about it, by the author who wrote the warning. **The honest figure is n=60 per
slice, 240 across four slices**, and the repetition count should be dropped from the config used to
produce the table until there is a stochastic target to justify it.

### D2 · "65 capabilities, 63 proofs" invites a question with no answer on the slide — **SEV-2**

Both integers are true and the gap is unexplained. `features.yaml` declares 65; `scripts/validate.py`
runs 63, because `validate.py:257` skips any feature whose `status != "done"` and **two are
`deferred`: F-008 and F-036**.

Worse for slide 3: the tool reports `OK: 63 done; ran 63`. That ratio **cannot fail on the count** —
it runs exactly the set it counts. Presenting "63/63" as though it were a coverage ratio invites the
one question a technical VP will actually ask. §2 has the wording that survives it.

### D3 · The `weak` separation number was engineered hours before it was measured — **SEV-2**

Revision 1 presents mutation `0.322` on the `weak` slice as a property of the instrument. It is, but
the causal order matters: PR #183 **changed how `weak` is built** (`_weakest_index`, selecting the
least discriminating grid point rather than the most), moving strict separation from **28 of 60 to
60 of 60**. The separation was designed in that morning and measured that afternoon.

That is legitimate corpus construction, not a fudge — a calibration fixture that fails to separate is
a broken fixture. But "our corpus discriminates" and "we built our corpus to discriminate, and
verified that it does" are different sentences, and only the second survives a follow-up question.
§3a now says the second.

### D4 · The proposed slide-2 line misattributes its own citation — **SEV-3**

Revision 1 proposed saying "the most recent audit found twenty-four such issues in our own work in a
single pass." [`../eval-delivery-sequencing/HYGIENE_AUDIT.md`](../eval-delivery-sequencing/HYGIENE_AUDIT.md)
says otherwise, in a section added specifically to prevent this: the audit found **20**; findings
**21–24 came from an automated review afterwards**, and one of those four was something the audit
had found and lost in consolidation. Quoting 24 as the audit's own number contradicts the document
it cites, on the exact axis — who found what — that the document was careful about.

### D5 · The instance arithmetic was wrong — **SEV-3**

Revision 1 argued "three reads as rigour, seven reads as unreliability." PLAN.md's slide 2 has three
*bullets* but four *defects* — its third bullet is "this cycle, **twice**" (F-062 and F-063).
Revision 1 added four more. The real move is **4 → 8**, which strengthens the argument rather
than weakening it: a doubling is a sharper change of message than 3→7.

### What revision 1 got right, and revision 2 keeps

- The central finding: the shipped config's perfect score is the corpus grading its own homework.
- The structural finding: Deck B is blocked on the *subject*, not on scorers. §4 now cites the code.
- The Deck A integer corrections (subject to D2's wording fix).
- The discrimination table's *shape* — separation on independent axes — which D1 does not touch.
  Only the denominator was wrong; every mean in the table is reproducible at n=60.

---

## The uncomfortable part, first

**The test-generation evaluation runs green today with a perfect score on every axis, and that
number is the corpus grading its own homework.**

```
run 'testgen-eval-e6321ce1' — 60 item(s)
  test_executability:            mean=1.000  pass_rate=1.00  n=60
  testgen_mutation_score:        mean=1.000  pass_rate=1.00  n=60
  testgen_green_on_correct:      mean=0.000  pass_rate=1.00  n=60
  requirement_obligation_recall: mean=1.000  pass_rate=1.00  n=60
QUALITY GATE: PASS
```

That is `config/testgen_eval.yaml` with `repetitions` set to 1 (see D1), run offline. Its dataset is
`corpora/testgen/v1/eval/thorough.jsonl` — **the corpus's own known-good reference suite**. Every
eval record supplies `inputs.suite` ready-made; verified, the `inputs` keys are
`focal_name, grid, mutants, obligations, reference, suite`. No agent produced it. No agent is in the
loop at any point.

A perfect score is the *correct* output here: it is the ceiling check, and it proves the pipeline end
to end. But `mutation_score = 1.000` on a slide, with the word "agent" anywhere near it, is exactly
the defect class this deck exists to claim the organisation prevents. §6 adds the rows PLAN.md's
"Numbers that must not appear" table needs.

---

## 1 · What PR #183 changed underneath the plan

PLAN.md was written against `a8a7d93`.

| PLAN.md says | Verified at `655de2e` | How |
|---|---|---|
| 63 declared capabilities, 61 run per-PR | **65 declared; 63 `done` and run; 2 `deferred`** | `python scripts/validate.py --tier fast`; `features.yaml` |
| 41 registered components | **45** | `census: 6 kind(s), 45 component(s)` |
| M8 credits 20 components | **43 of 45**, the 2 uncredited being exactly the 2 waived by name | `docs/matrix-coverage.md` |
| Blocker **B4** — `prove-m8-execution` task 4 outstanding | **closed** | change implemented, pending archive |
| Deck B needs `add-testgen-eval-matrix` implemented | **implemented and merged** (F-065, ADR 0043) | PR #183 |
| Slide 2: "three times our own gates were wrong" | **four defects then; eight now** — see §3b | HYGIENE_AUDIT.md |

`./demo/run_demo.sh` still exits 0 with six reports at `655de2e`, re-verified today, and prints no
credential warning. Slide 7 is intact.

---

## 2 · Deck A corrections — mechanical, do these first

| Slide | Change |
|---|---|
| 3 | Not "63 capabilities, 61 proofs" and **not** "65 and 63" bare. Say: **"63 capabilities, each with an executable proof, and all 63 run on every pull request. Two more are declared and deferred; their proofs do not run, and the ledger says so."** That volunteers D2's gap instead of inviting it |
| 4 | "41 components × 6 dimensions" → **"45 components × 6 dimensions"** |
| 5 | Add the breadth: composability is credited by observed execution for **43 of 45** components, the other two waived in the generated doc *with the reason*. The waiver text is the point — a component absent with no explanation is indistinguishable from one nobody considered |
| 9 | "zero scenario scorers implemented" is **no longer true**. Replace per §4 |
| new | The discrimination table (§3a), with §3a's labelling |

---

## 3 · The new asset, and the slide-2 problem

### 3a · Four slices, 60 items each, offline and deterministic

Same config, only the dataset path changed; `repetitions: 1`, because more adds nothing (D1).

| corpus slice | executability | mutation score | false-alarm rate | obligation recall |
|---|---|---|---|---|
| `thorough` — known-good | 1.000 | 1.000 | 0.000 | 1.000 |
| `weak` — known-bad (detection) | 1.000 | **0.322** | 0.000 | **0.260** |
| `false_alarm` — known-bad (precision) | 1.000 | 1.000 | **0.397** | 1.000 |
| `broken` — non-executable | **0.000** | n/a | n/a | n/a |

*(Means measured at `repetitions: 5`, n=300; identical at `repetitions: 1`, n=60. Report **60**.)*

**Say it in this order, and do not skip the first clause:** *we built a corpus with known-good and
known-bad suites specifically so the scorers could be checked against a known answer, and here is the
check.* Three properties then carry the slide:

1. **Each known-bad slice moves only its own axis.** `weak` drops detection and leaves the false-alarm
   rate at zero; `false_alarm` raises *only* the false-alarm rate and leaves mutation and recall at
   1.000. A single blended "test quality score" would collapse both into the same middling number and
   hide which failure occurred.
2. **`broken` reports `n/a`, not `0.0`** on the three dependent scorers — "absent evidence is not a
   zero", visible in the output rather than asserted in a docstring.
3. **The advisory gate observably works**: every breach prints `~ (advisory, non-blocking)` and the
   run still ends `QUALITY GATE: PASS`. That is F-062's `report_only` demonstrated.

What it is: **the measurement instrument checked against fixtures with known answers.** What it is
not: an agent result, or evidence that the corpus is hard.

### 3b · Slide 2 is now stronger and riskier at once

PR #183 added four more instances of "our own gates were wrong", one better than any original three:
a scorer emitted a **mutation score of 2.0** — a rate above 1.0 — from a real target run into a gate
rule that takes the mean. Also: `secret scan (gitleaks)` could report green having never run; the
live eval corpus sat in no workflow filter and no protected pattern; and a guard function could be
replaced with `return False` with the entire suite still passing.

That takes slide 2 from **four defects to eight** (D5).

**The risk:** four reads as rigour; eight reads as "your gates are unreliable." The difference is
framing and whether the trend is visibly toward fewer and earlier.

**Recommended re-cut.** Keep **three** instances — one historical (F-049), one structural (M8
composability), one from this cycle (the 2.0) — then one line doing the work of the other five:

> "Every one of these was found by us, before it changed a decision, and each closed with a guard
> that fails if it recurs. A single audit pass over our own most recent work found twenty more; an
> automated review then found four the audit had missed, one of which the audit had found and lost.
> That last one is why the audit now records who found what."

That converts a lengthening list of embarrassments into a demonstrated *rate of self-detection*, and
its numbers match [`HYGIENE_AUDIT.md`](../eval-delivery-sequencing/HYGIENE_AUDIT.md) exactly — which
revision 1's version did not (D4). Volunteering the "an automated review caught four we missed" beat
is stronger than omitting it: it is the only part a sceptic could otherwise discover unaided.

---

## 4 · The revised deck ladder

### Deck A — "the measurement system" · **available today**, with §2's corrections

### Deck A+ — "and the instrument is checked against known answers" · **~1 day**

Deck A plus §3a plus a rehearsal pass. No engineering: run four commands, paste a table, write the
two sentences that keep it from being read as an agent result. Highest return per hour available.

### Deck B — "first agent results" · **not scorer-blocked; blocked on the subject**

> **Nothing in the harness makes an agent write a test suite**, and nothing chains two targets.
> `src/eval_harness/config/models.py:384` gives a run exactly one `target: ComponentSpec`. The
> multi-target feature that exists (`CompareSpec`, F-024, `models.py:266-273`) runs the same dataset
> against several targets **side by side, not in sequence**. The corpus supplies `inputs.suite`
> ready-made; the registered targets are `echo`, `callable`, `model`.

So Deck B needs a *new composition*: focal method + obligations → generated suite → the existing
execution target. That is a design decision of the same class as ADR 0043, not a config change.
Everything downstream of it already exists and is measured.

**Do not estimate it yet.** The engineering is plausibly small; the evaluation design is not — prompt
held constant or tuned per item, one attempt or many, how the held-out split is enforced, and whether
a model target inside an eval run may touch the network at all under the offline-suite rule. Write
the proposal, then estimate.

### Deck C — unchanged, ~3 sprints plus the governance decision

---

## 5 · Work items, in order

| # | Item | Size | Unblocks |
|---|---|---|---|
| 1 | Apply §2's corrections wherever the deck is drafted, including D2's wording | minutes | correctness in the room |
| 2 | Re-cut slide 2 per §3b — three instances plus the self-detection line | ~1 hour | the deck's strongest slide staying strong |
| 3 | Add §3a's table with its labelling, at **n=60** | ~1 hour | **Deck A+** |
| 4 | Add §6's rows to PLAN.md's "must not appear" table | minutes | the one error that would discredit the deck |
| 5 | Run the rehearsal checklist on the presenting machine | ~1 hour | slide 7 |
| 6 | Write the agent-in-the-loop change proposal | ~half day | an honest Deck B estimate |
| 7 | Drop `repetitions: 5` from `config/testgen_eval.yaml`, or state in the file why it is there before a stochastic target exists | ~15 min | stops D1 recurring |
| 8 | Archive the three implemented OpenSpec changes | ~1 hour each | tidies the story; not deck-blocking |

Items 1–5 are Deck A+ and total under a day. Item 6 converts Deck B from a guess into a date.

---

## 6 · Additions to PLAN.md's "Numbers that must not appear"

| Do not say | Why | Say instead |
|---|---|---|
| "our test generation scores 1.0 on mutation / executability / recall" | That run scores the **corpus's own reference suite**; `inputs.suite` is pre-supplied and no agent is in the loop | "the instrument separates known-good from known-bad: 1.000 vs 0.322 mutation, 0.000 vs 0.397 false-alarm rate, 60 items per slice" |
| "we measured our agents at test generation" | Nothing generates a suite from an agent; nothing chains targets — §4 | "scorers, corpus and execution sandbox are done and checked; the agent-in-the-loop step is the next change" |
| "n=300" for any testgen figure | 5 identical repetitions of 60 deterministic items — D1 | **"n=60"** |
| "63 capabilities / 41 components" | Stale as of `655de2e` | 63 done (+2 deferred); 45 components |
| "63 of 63 validators pass" *as a coverage ratio* | The tool runs exactly the set it counts; it cannot fail on the count | "every capability marked done carries a proof, and all of them run per PR" |
| "zero scenario scorers implemented" | Four are merged | "four implemented; no agent measured through them yet" |
| "the audit found 24 issues" | The audit found 20; a review found 4 more — D4 | "20 from the audit, 4 more from an automated review afterwards" |

---

## 7 · Blockers

| # | Blocker | Status |
|---|---|---|
| B1 | CHARTER §4 invariant 7 — real incident telemetry is host-specific | **open**, unchanged |
| B2 | Zero `HUMAN_AUDIT` labels; ~200–350 paired labels per judged scorer | **open**. *(Figure recorded 2026-08-05 — re-query the store before quoting it)* |
| B3 | Protected-path review latency | **open**. PR #183 is one data point: 18 commits, same-day merge. One sample is not a turnaround target |
| B4 | `prove-m8-execution` task 4 | **CLOSED** |
| B5 | *(new)* No agent-in-the-loop step, and no target chaining | **open** — Deck B's critical path |

PLAN.md's three asks are unchanged and still correct.

---

## 8 · Rehearsal, revised

PLAN.md's checklist stands, plus:

- [ ] Run the four soak commands **before** the room — ~30 s each at `repetitions: 1` — and show the
      table rather than the run.
- [ ] Rehearse "this is not an agent result" until it is automatic. It will be the first question.
- [ ] Rehearse the answer to "why 65 and 63?" — two deferred features, named. D2 exists because that
      pause is avoidable.
- [ ] Know the advisory-breach lines cold. `~ (advisory, non-blocking)` beside `QUALITY GATE: PASS`
      is the deck's most concrete demonstration that a threshold can be measured without being
      enforced.

---

## Scope limit of this document's method

Every figure above about **this repository** was produced by running the command shown, at
`655de2e`. Figures inherited from PLAN.md about the **outside world** — the 12.5% / 22.4% benchmark
result, Meta's 20% DrP figure, the κ sample-size arithmetic — were verified by
[`./REVIEW.md`](./REVIEW.md) and are **not** re-verified here. If any of them reaches a slide, re-read
REVIEW.md Part C first; this document's "everything was run" claim does not extend to them.

## Reproducing every figure

```bash
python scripts/validate.py --tier fast                      # 63 done; ran 63
python scripts/validations/F_063.py | grep census           # 45 components
./demo/run_demo.sh                                          # exit 0, six reports
# n=60 per slice; repeat with weak.jsonl, false_alarm.jsonl, broken.jsonl
EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=eval_harness.targets.testgen \
  python -m eval_harness.cli run --config config/testgen_eval.yaml
```

## Related documents

- [`./PLAN.md`](./PLAN.md) — which deck, and slide by slide
- [`./REVIEW.md`](./REVIEW.md) — the two-pass peer review, including A18's rejection of an earlier VP
  framing, and Part C's citation checks this document does not repeat
- [`../eval-delivery-sequencing/HYGIENE_AUDIT.md`](../eval-delivery-sequencing/HYGIENE_AUDIT.md) —
  the 20 + 4 findings behind §3b, and what remains open
- [`../../decisions/0043-testgen-evaluation-seam.md`](../../decisions/0043-testgen-evaluation-seam.md) —
  the seam §3a rests on, and the determinism claim behind D1

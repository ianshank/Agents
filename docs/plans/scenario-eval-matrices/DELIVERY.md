# Delivery Plan — getting the VP presentation into the room

**ID:** PLAN-2026-09-05-vp-delivery
**Date:** 2026-09-05 · **Base commit:** `655de2e` (merge of PR #183)
**Companion to:** [`./PLAN.md`](./PLAN.md), which decides *which deck*. This decides *how it gets
delivered*, and records what PR #183 changed underneath it.
**Non-goals:** writing the deck; re-litigating the deck choice (Deck A first still holds, and §3
strengthens the case rather than reopening it).

Every number below was produced by running something in this checkout at `655de2e`, today. Where a
figure came from reading rather than running, it says so.

---

## The uncomfortable part, first

**The test-generation evaluation runs green today with a perfect score on every axis, and that
number is the corpus grading its own homework.**

```
run 'testgen-eval-b22cab31' — 300 item(s)
  test_executability:            mean=1.000  pass_rate=1.00  n=300
  testgen_mutation_score:        mean=1.000  pass_rate=1.00  n=300
  testgen_green_on_correct:      mean=0.000  pass_rate=1.00  n=300
  requirement_obligation_recall: mean=1.000  pass_rate=1.00  n=300
QUALITY GATE: PASS
```

That is the shipped config, unmodified, run offline in about three minutes. Its dataset is
`corpora/testgen/v1/eval/thorough.jsonl` — **the corpus's own known-good reference suite**. The
`suite` field of every eval record is pre-supplied by the generator (verified: `inputs` keys are
`focal_name, grid, mutants, obligations, reference, suite`). No agent produced it. No agent is in
the loop at any point.

A perfect score is the *correct* output here: it is the ceiling check, and it proves the pipeline
end-to-end. But `mutation_score = 1.000` on a slide, with the word "agent" anywhere near it, is
exactly the defect class this deck exists to claim the organisation prevents — a number that looks
like a measurement of something and is a measurement of nothing. **PLAN.md's "Numbers that must not
appear" table needs a new row before anyone opens a slide editor.** It is added in §6.

The second uncomfortable thing is smaller and easier to fix: **PLAN.md's Deck A evidence table is
now wrong in four places.** Not stale in spirit — wrong in the specific integers a technical VP will
see on screen when the live commands run. §2 lists them.

---

## 1 · What PR #183 changed underneath the plan

PLAN.md was written against `a8a7d93`. It is now three sprints' worth of assumptions out of date in
one direction (better) and one integer out of date in several places (worse).

| PLAN.md says | Verified at `655de2e` | Where |
|---|---|---|
| 63 declared capabilities, 61 run per-PR | **65 capabilities, 63 run per-PR, 63/63 green** | `python scripts/validate.py --tier fast` |
| 41 registered components | **45** | `census: 6 kind(s), 45 component(s)` |
| M8 credits 20 components | **43 of 45**, the 2 uncredited being exactly the 2 waived by name | `docs/matrix-coverage.md` |
| Blocker **B4** — `prove-m8-execution` task 4 outstanding | **closed** | change is implemented, pending archive |
| Deck B needs `add-testgen-eval-matrix` implemented | **implemented and merged** (F-065, ADR 0043) | PR #183 |
| Slide 2: "three times our own gates were wrong" | **the count is now materially higher** | §3 |

`./demo/run_demo.sh` still exits 0 with six reports at `655de2e` — re-verified today, on this
checkout. That is slide 7 and it is intact.

---

## 2 · Deck A corrections — mechanical, do these first

Four integer edits and one addition. None requires new work; all are one-line changes to a deck
that does not exist yet, so the cost is only in *not* forgetting them.

| Slide | Change |
|---|---|
| 3 | "63 capabilities, 61 executable proofs per PR" → **"65 capabilities, 63 executable proofs, every one run per PR"** |
| 4 | "41 components × 6 dimensions" → **"45 components × 6 dimensions"** |
| 5 | Add the breadth number: composability is not merely *defined* as observed execution, it is **credited that way for 43 of 45 components**, with the remaining two waived in the generated doc alongside the reason. The waiver text is the point: a component absent with no explanation is indistinguishable from one nobody considered |
| 9 | The honesty slide's first bullet, "zero scenario scorers implemented", is **no longer true** — four are implemented and merged. Replace it with the sharper version in §4 |
| new | The discrimination table (§3). It is the strongest new asset and it did not exist when PLAN.md was written |

---

## 3 · The new asset: measured discrimination, and the slide-2 problem

### 3a · Four slices, 1,200 measurements, offline and deterministic

Run today against the four committed corpus slices — same config, only the dataset path changed.
Each slice is 60 items × 5 repetitions = **n=300**.

| corpus slice | executability | mutation score | false-alarm rate | obligation recall |
|---|---|---|---|---|
| `thorough` — known-good | 1.000 | 1.000 | 0.000 | 1.000 |
| `weak` — known-bad (detection) | 1.000 | **0.322** | 0.000 | **0.260** |
| `false_alarm` — known-bad (precision) | 1.000 | 1.000 | **0.397** | 1.000 |
| `broken` — non-executable | **0.000** | n/a | n/a | n/a |

Three properties are visible in that table and each is worth a sentence out loud:

1. **Each known-bad slice moves only its own axis.** `weak` drops detection (mutation, recall) and
   leaves the false-alarm rate at zero. `false_alarm` raises *only* the false-alarm rate and leaves
   mutation and recall at 1.000. A single blended "test quality score" would collapse both into the
   same middling number and hide which failure occurred.
2. **`broken` reports `n/a`, not `0.0`.** Three scorers return not-applicable rather than a failing
   score, because a mutation score over a suite that never ran is meaningless, not low. That is the
   "absent evidence is not a zero" rule, visible in the output rather than asserted in a docstring.
3. **The advisory gate is observably working.** Every threshold breach prints
   `~ (advisory, non-blocking)` and the run still ends `QUALITY GATE: PASS`. That is F-062's
   `report_only` — an uncalibrated scorer measured inside a gate that stays live for everything
   else — demonstrated rather than described.

This is a real slide, and an honest one, provided it is labelled for what it is: **the measurement
instrument separating known-good from known-bad fixtures.** It is not an agent result.

### 3b · Slide 2 is now stronger and riskier at the same time

PLAN.md calls slide 2 ("three times our own gates were wrong, and how we caught them") the deck's
strongest slide. PR #183 added more instances, and at least one is better than any of the original
three:

- A scorer emitted a **mutation score of 2.0** — a rate above 1.0 — from a real target run, into a
  gate rule that takes the mean across items. Found by an audit of our own just-written code, root
  caused to three independent defects at three layers, fixed, negative-controlled, merged same day.
- `secret scan (gitleaks)` could report **green having never run**: a `paths:` filter is evaluated
  per workflow, so a docs- or corpus-only PR skipped the workflow and its companion stub posted the
  passing context anyway.
- `corpora/**` — the live eval dataset — was in **no** workflow filter and **no** protected pattern,
  so a corpus-only PR ran zero workflows behind seven green required checks.
- A guard function could be replaced with `return False` and the **entire test suite still passed**.

**The risk nobody has flagged yet:** three instances reads as rigour. Seven reads as "your gates are
unreliable." The difference is entirely in the framing and in whether the trend is visibly toward
fewer and earlier. Do not simply append the new ones to the existing list.

**Recommended re-cut.** Keep slide 2 to **three** instances — one historical (F-049), one structural
(M8 composability), one from this cycle (the 2.0). Then add one line that does the work the other
four would have done:

> "Each of these was found by us, before it mattered, and each one closed with a guard that fails if
> it recurs. The most recent audit found twenty-four such issues in our own work in a single pass;
> the four in front of you are the ones that would have changed a number."

That converts a lengthening list of embarrassments into a demonstrated *rate of self-detection*,
which is the property actually being sold. It also volunteers the number 24 rather than waiting for
someone to find `HYGIENE_AUDIT.md`, which is public in the repository either way.

---

## 4 · The revised deck ladder

PLAN.md's ladder was A (today) → B (~1 sprint) → C (~3 sprints). The middle rung moved, and a new
rung appeared beneath it.

### Deck A — "the measurement system" · **available today**, with §2's corrections

Unchanged in thesis, stronger in evidence. Give it.

### Deck A+ — "and the instrument is calibrated against known-good and known-bad" · **~1 day**

New. It is Deck A plus §3a's table plus one rehearsal pass. The work is not engineering: it is
running four commands, pasting a table, and writing two sentences of labelling that keep it from
being mistaken for an agent result. **This is the highest return per hour available.**

### Deck B — "first agent results" · **no longer scorer-blocked; now blocked on the subject**

PLAN.md sized Deck B as "implement `add-testgen-eval-matrix`". That is done. The remaining gap is
different in kind and was not previously stated:

> **Nothing in the harness makes an agent write a test suite.** The corpus supplies `inputs.suite`
> ready-made; the target executes it. The three registered targets are `echo`, `callable` and
> `model`. Measuring an agent requires a step that turns a focal method plus its obligations into a
> generated suite, and then feeds that suite to the existing target.

Verified by reading `corpora/testgen/v1/eval/thorough.jsonl` and
`src/eval_harness/targets/__init__.py`. This is a two-stage pipeline or a new composite target, and
it is a genuinely new piece of design — the same class of decision as ADR 0043, not a config change.
Everything downstream of it already exists and is measured.

**Size honestly, do not guess.** The engineering is plausibly small; the *evaluation* design is not:
prompt held constant or tuned per item, one attempt or `repetitions` attempts, held-out split
enforced how, and whether a model target inside an eval run is permitted to touch the network at all
under the offline-suite rule. Write that as a change proposal before estimating it.

### Deck C — unchanged, still ~3 sprints plus the governance decision

---

## 5 · Work items, in order

| # | Item | Size | Unblocks |
|---|---|---|---|
| 1 | Apply §2's four integer corrections wherever the deck is drafted | minutes | correctness in the room |
| 2 | Re-cut slide 2 per §3b — three instances plus the self-detection-rate line | ~1 hour | the deck's strongest slide staying strong |
| 3 | Add §3a's discrimination table as a slide, with the "not an agent result" label | ~1 hour | **Deck A+** |
| 4 | Add the new row to PLAN.md's "must not appear" table (§6) | minutes | prevents the one error that would discredit the deck |
| 5 | Run the full rehearsal checklist on the presenting machine | ~1 hour | slide 7 |
| 6 | Write the agent-in-the-loop change proposal (Deck B's real gap) | ~half day | an honest Deck B estimate |
| 7 | Archive the three implemented OpenSpec changes (`prove-m8-execution`, `add-testgen-eval-matrix`, `add-gate-decision-provenance`) | ~1 hour each | tidies the story; not deck-blocking |

Items 1–5 are the whole of Deck A+ and total under a day. Item 6 is what converts Deck B from a
guess into a date.

---

## 6 · Additions to PLAN.md's "Numbers that must not appear"

| Do not say | Why | Say instead |
|---|---|---|
| "our test-generation scores 1.0 on mutation / executability / recall" | That run scores the **corpus's own reference suite**. No agent is in the loop; `inputs.suite` is pre-supplied | "the instrument separates known-good from known-bad: 1.000 vs 0.322 mutation, 0.000 vs 0.397 false-alarm rate, n=300 per slice" |
| "we measured our agents at test generation" | Nothing generates a suite from an agent yet — see §4 | "the scorers, corpus and execution sandbox are done and measured; the agent-in-the-loop step is the next change" |
| "63 capabilities / 41 components" | Both stale as of `655de2e` | 65 and 45 |
| "zero scenario scorers implemented" | Four are merged | "four implemented; no agent measured through them yet" |

---

## 7 · Blockers

| # | Blocker | Status |
|---|---|---|
| B1 | CHARTER §4 invariant 7 — real incident telemetry is host-specific | **open**, unchanged. Still the ask |
| B2 | Zero `HUMAN_AUDIT` labels; ~200–350 paired labels needed per judged scorer | **open**, unchanged. *(Figure recorded 2026-08-05 — re-query the store before quoting it)* |
| B3 | Protected-path review latency under single-maintainer branch protection | **open**, and PR #183 is now a data point: 18 commits, same-day merge. One sample, not a turnaround target |
| B4 | `prove-m8-execution` task 4 | **CLOSED** |
| B5 | *(new)* No agent-in-the-loop step for test generation | **open** — this is Deck B's critical path, not scorers |

The three asks in PLAN.md are unchanged and still correct. B3's ask can now cite a real turnaround
instead of asking in the abstract.

---

## 8 · Rehearsal, revised

PLAN.md's checklist stands. Three additions:

- [ ] The four soak commands are now part of the demo surface. Run them on the presenting machine —
      each slice takes ~3 minutes, so run them **before** the room, not in it, and show the table.
- [ ] Rehearse the "this is not an agent result" sentence until it is automatic. It will be the
      first question, and answering it before it is asked is the whole value of the slide.
- [ ] Know the four advisory-breach lines cold. `~ (advisory, non-blocking)` beside
      `QUALITY GATE: PASS` is the single most concrete demonstration in the deck that a threshold
      can be measured without being enforced — which is the mechanism that lets an uncalibrated
      metric exist honestly.

---

## Reproducing every figure in this document

```bash
python scripts/validate.py --tier fast                      # 63/63
python scripts/validations/F_063.py | grep census           # 45 components
./demo/run_demo.sh                                          # exit 0, six reports
EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=eval_harness.targets.testgen \
  python -m eval_harness.cli run --config config/testgen_eval.yaml
# then repeat with the dataset path pointed at weak.jsonl, false_alarm.jsonl, broken.jsonl
```

## Related documents

- [`./PLAN.md`](./PLAN.md) — which deck, and slide by slide
- [`./REVIEW.md`](./REVIEW.md) — the two-pass peer review behind it, including A18's rejection of an
  earlier VP framing
- [`../eval-delivery-sequencing/HYGIENE_AUDIT.md`](../eval-delivery-sequencing/HYGIENE_AUDIT.md) —
  the 24 findings behind §3b, and what remains open
- [`../../decisions/0043-testgen-evaluation-seam.md`](../../decisions/0043-testgen-evaluation-seam.md) —
  the target-executes/scorers-read seam the §3a table rests on

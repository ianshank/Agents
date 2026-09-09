# Deck A+ — speaker notes and corrected slide copy

**Companion to:** [`PLAN.md`](./PLAN.md), [`DELIVERY.md`](./DELIVERY.md) revision 2  
**Purpose:** presentation-ready wording for Deck A / A+. Not the slide deck itself.  
**Status:** ready after day-of rehearsal (checklist below).  
**Deck B:** agent-in-the-loop testgen landed as F-069 / ADR 0048 (`#217`); remaining Deck B work is a live agent writing a suite, not the design. See [`openspec/changes/archive/add-agent-in-the-loop-testgen/`](../../../openspec/changes/archive/add-agent-in-the-loop-testgen/).

---

## Frame (say this once, up front)

We are presenting the **measurement system**, not agent league tables.  
The shipped test-generation config can score **1.000 on every axis** today. That number is the corpus grading its own known-good reference suite. No agent wrote those tests. Deck B is where agent-generated suites enter; it needs a design change first.

---

## Slide-by-slide copy

### Slide 1 — Title
**Title:** How we know an eval number is real  
**Subtitle:** Agents monorepo — measurement system (Deck A+)  
**Do not say:** "agent performance results" or "we measured our agents at test generation."

### Slide 2 — We catch our own false greens (4 → 8)
**Line:** "This cycle we caught **eight** defects in our own measurement story — four named earlier, then four more when delivery was adversarially re-checked."

**Say:**
- Four earlier integrity defects (including gate-decision provenance and M8 execution vacuity fixes).
- Delivery revision 2 then found **five** issues in our own VP wording (D1–D5): four content defects (D1–D4) plus D5, which is an **arithmetic correction** (the true self-caught count is 4→8, not 3→7). On the slide, count D5 with the second wave as the fourth added beat — do not say "five more" in the spoken line.
- Hygiene audit found **20** issues; an automated review afterwards found **4** more. Do **not** say "the audit found 24."

**Citation discipline:** "20 from the hygiene audit, 4 from an automated review afterwards."

### Slide 3 — Capabilities vs proofs (D2 wording)
**Say exactly:**  
"We declare **65** capabilities. **63** have executable proofs that run on every pull request. **Two** are declared and deferred — F-008 and F-036 — their proofs do not run, and the ledger says so."

**Do not say:** "63/63" or "65 capabilities, 63 proofs" without naming the deferred pair. The validator runs exactly the `done` set, so a bare 63/63 ratio cannot fail on the count.

### Slide 4 — What the matrix actually measures
- M1–M7: method-count floors with waivers named in `docs/matrix-coverage.md`.
- M8: **execution-verified** pipelines — a cell is not credit for appearing in config. Tip credits **39 of 41** components; `bedrock` and `phoenix_evals` are waived with reasons (CI install / pin conflicts).
- Stale plan text that said "M8 task 4 outstanding" is wrong on tip — breadth landed.

### Slide 5 — Test-generation instrument (honest)
**Say:** Scorers, synthetic corpus, and sandboxed suite execution shipped (F-065). Four pure scorers: executability, mutation score, green-on-correct, obligation recall. Advisory gates only.

**Then the honesty beat:** On `thorough.jsonl` with the corpus's own reference suite, means are 1.000 / 1.000 / 0.000 / 1.000. That is a **calibration fixture**, not an agent result.

### Slide 6 — Discrimination table (Deck A+ asset) — **n=60**
Reproduce offline (allowlist required):

```bash
EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=eval_harness.targets.testgen \
  eval-harness run --config config/testgen_eval.yaml
# then point dataset.path at:
#   corpora/testgen/v1/eval/thorough.jsonl
#   corpora/testgen/v1/eval/weak.jsonl
#   corpora/testgen/v1/eval/false_alarm.jsonl
#   corpora/testgen/v1/eval/broken.jsonl
```

| Slice | What it pins | Report as |
|---|---|---|
| thorough | known-good reference suite | n=**60** |
| weak | intentionally weak suite | n=**60** |
| false_alarm | false-alarm shape | n=**60** |
| broken | broken shape | n=**60** |

**Denominator rule (D1):** Never say n=300. `repetitions: 5` × 60 deterministic items is a 5× multiplier with **zero new information** until a stochastic target exists. Honest figure: **n=60 per slice, 240 across four slices**.

**Weak separation (D3):** Say "we built the weak slice to discriminate, then verified that it does" — not "our corpus was discovered to discriminate."

### Slide 7 — Live fail-closed demo
Run on the presenting machine the day of: `demo/run_demo.sh` from a clean clone.  
Pre-open `out/demo/report-fail.html`.  
Know cold: `helpfulness.mean=0.844` against `min 0.95`, process exit 1. The point is CI stops.

### Slide 8 — What is not measured yet
- No agent-written suites in the loop (Deck B blocked on target chaining).
- RCA and requirements scenario matrices: OpenSpec proposed, not implemented.
- Judge-gated metrics stay advisory until HUMAN_AUDIT mass exists (~200–350 paired labels per judged scorer is the planning figure; re-query the store before quoting live counts).
- `main` branch protection / required checks: owner action (ADR 0037) — gates are still advisory at merge until applied.

### Slide 9 — Honesty (rehearse out loud)
Volunteer before asked:
1. No agent performance numbers yet.
2. Perfect testgen scores on the shipped config are self-grading.
3. Deck B needs an agent-in-the-loop design, not more scorers.
4. Calibration figures without labels are empty queries.

### Slide 10 — The ask (three decisions)
1. **B1:** Real incident telemetry under a CHARTER §3 amendment, or synthetic-only RCA permanently.
2. **B2:** Who produces HUMAN_AUDIT labels, and by when.
3. **B3:** CODEOWNER / `eval-change-approved` turnaround target so sprint dates mean something.

---

## Numbers that must not appear

| Do not say | Why | Say instead |
|---|---|---|
| "n=300" for any testgen figure | 5 identical repetitions of 60 deterministic items (D1) | **"n=60"** |
| "we measured our agents at test generation" | No agent generates a suite; no target chaining | "scorers, corpus, and sandbox are done; agent-in-the-loop is next" |
| "63/63 proofs" as coverage | Validator runs only `done` features | Name 63 runnable + 2 deferred |
| "the audit found 24 issues" | Audit 20; review +4 (D4) | "20 from the audit, 4 from an automated review afterwards" |
| "OpenRCA agents went 10% → 33%" | Vendor self-report vs independent 12.5% | Independent full-benchmark figures only |
| "a trivial heuristic scores 36.5%, beating agents" | Invalid cross-pool comparison | Measure our floor on our corpus |
| "35.9% of Java PRs improve coverage" | Wrong denominator | Instrumented code-plus-tests PRs |
| "industry sees 30–70% MTTR reduction" | Unsourced | Cite audited figures only |
| any κ / ECE / Brier / AUROC as live results | Nothing to compute without labels | "instrumented; labels are the dependency" |
| "200 paired labels → κ CI width 0.10" | Off by 4–6× | Use half-width language correctly |

---

## Rehearsal checklist

- [ ] `demo/run_demo.sh` on the presenting machine, clean clone, **day of**
- [ ] `out/demo/report-fail.html` already open
- [ ] Know `helpfulness.mean=0.844` vs min 0.95, exit 1
- [ ] Optional: `validate.py --tier fast` only if the room is technical
- [ ] Rehearse slide 9 out loud (volunteer gaps; do not apologize)
- [ ] Rehearse answer to "why 65 and 63?" — two deferred features, named
- [ ] Discrimination table printed at n=60; no n=300 anywhere in the deck
- [ ] Confirm `repetitions` story: inert for deterministic callable until stochastic target

---

## Related

- [`DELIVERY.md`](./DELIVERY.md) — D1–D5, work items 1–8  
- [`PLAN.md`](./PLAN.md) — deck ladder, blockers B1–B4  
- [`openspec/changes/archive/add-agent-in-the-loop-testgen/`](../../../openspec/changes/archive/add-agent-in-the-loop-testgen/) — Deck B unlock proposal (archived; F-069 landed)  
- [`docs/matrix-coverage.md`](../../matrix-coverage.md) — M8 execution census  

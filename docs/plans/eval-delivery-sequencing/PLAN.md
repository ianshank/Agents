# Implementation Plan — Eval Delivery Sequencing

**ID:** PLAN-2026-09-05-eval-delivery-sequencing
**Date:** 2026-09-05 · **Base commit:** `d7deacf`
**Motivated by:** F-062 and F-063 landing (PRs #181, #182), which cleared the two prerequisites
the three scenario-eval matrices were queued behind — and by a provenance defect found while
verifying F-063's own `implemented_in` ref.
**Scope:** decide what the eval workstream does next, in what order, and which steps are blocked
on a human rather than on engineering. Ordering and gating only.
**Non-goals:** restating the two plans that already own their workstreams (see *Ownership*
below); designing the three scenario matrices (their OpenSpec packages hold that detail);
any change to a gate's semantics.

> Not [`NEXT_STEPS.md`](../../../NEXT_STEPS.md) at the repository root, which is a ledger of
> landed work and named deferrals. This document is forward-looking and sequencing-only.

---

## The uncomfortable part, first

**Three of the four candidate workstreams are blocked on decisions no engineer can make, and the
sprint plan in the sibling document does not say so loudly enough.** `add-rca-eval-matrix` needs
B1 (CHARTER §4 invariant 7) settled or it stays synthetic forever. Every judge-backed scorer
needs B2 (funded human labels) or it is advisory forever. `add-measurement-harness-wedge` needs a
CHARTER §3 ratified amendment with GOVERNANCE sign-off, a secret rotation, and a package rename
over third-party trademarks — none of which is code.

What is genuinely unblocked and engineering-only is narrow: the provenance guard below,
`prove-m8-execution` task 4, and `add-testgen-eval-matrix` — which was deliberately designed to
ship no judge, precisely so it would not queue behind calibration.

So the plan is not "pick the most valuable change". It is: **spend the unblocked engineering
capacity on WS-1 → WS-2 → WS-3 in that order, and put the three decisions in front of a human
this week, because everything past WS-3 is a hope until they are answered.**

**Second uncomfortable point: the feature registry's core claim is currently unverified.** 61
features assert `implemented_in: <sha>`. The check proves those SHAs are *commits*. It does not
prove they are *in main*. One is not. Details in WS-1.

---

## Ownership — what this plan does not own

| Workstream | Owner document | This plan's role |
|---|---|---|
| M8 semantics, enforcement-before-evidence, the 41-component widening | [`plans/eval-evidence-integrity/PLAN.md`](../eval-evidence-integrity/PLAN.md) | Order it, size it, discharge its stated precondition |
| VP narrative, decks, the three-scenario story, blockers B1–B4 | [`plans/scenario-eval-matrices/PLAN.md`](../scenario-eval-matrices/PLAN.md) | Correct two claims in it (below); do not restate it |
| Per-change design and tasks | `openspec/changes/<id>/` | Reference; never duplicate |

An entry here that contradicts an owner document is a defect in this document, not a decision.

---

## Current state, measured at `d7deacf`

Everything in this section was executed against this checkout, not recalled.

**M8 composability — 20 of 41 credited, 2 waived, 19 outstanding.**

| Kind | Uncredited components |
|---|---|
| dataset | `braintrust`, `csv`, `jsonl`, `langfuse`, `parquet` |
| judge | `panel` (`bedrock`, `phoenix_evals` waived with named reasons) |
| scorer | `autoevals`, `json_keys`, `policy_violation`, `regex_match`, `state_transition` |
| sink | `braintrust`, `html_file`, `langfuse`, `phoenix` |
| state_adapter | `filesystem`, `mock_http`, `sqlite` |
| target | `model` |

**Open task counts in the proposed OpenSpec packages:** measurement-wedge 44 · testgen 30 · rca
29 · requirements-gen 29. All are 0-done.

**Provenance:** 61 `implemented_in` refs. All 61 resolve. **60 are ancestors of `HEAD`; one is
not.**

---

## WS-1 — Provenance ancestry guard · *unblocked · ~1 day · do first*

### The defect

`scripts/validate.py:235` verifies a ref this way:

```python
git rev-parse --verify --quiet "<ref>^{commit}"
```

That asks *"is this a commit?"*, not *"did it land?"*. Anything present in the object store
passes — an orphan reachable only via reflog, or a commit on an unmerged branch. CI runs
`--strict-git` at `quality-gates.yml:172` with `fetch-depth: 0`, which fetches **every branch**,
so an unmerged branch's commit resolves there too.

The repository already met the resolvability half of this problem and fixed it — the comment at
`quality-gates.yml:165-171` records six SHAs that "rotted away" from squash-merged branches. Its
mitigation for the remaining half is a **convention** ("keep merge commits"), not a check. A
convention is not a guard, and one ref has already slipped past it.

### The instance

`F-040` records `implemented_in: 0f19ecaa8…`, which exists only on
`origin/feat/F-040-soak-stats`. The feature did land — via PR #113 from
`feat/F-040-soak-stats-**rebased**`, as commit `3e26747a7be62eb91c1ebac6985d916b32ab7cdc`. So
`status: done` is correct and the pointer is stale: the rebase orphaned it, and because the
pre-rebase branch still exists on the remote, `--strict-git` sees a perfectly resolvable commit.

This is the same failure mode that orphaned F-063's SHA two days ago. That one was caught by
hand. This one was not caught for six weeks.

### The fix, and why it needs no exemption list

Add an ancestry assertion beside the existing resolvability one:

```python
git merge-base --is-ancestor "<ref>" HEAD
```

`HEAD`, not `origin/main`, is the load-bearing choice. A PR that stamps its own feature's SHA
records a commit on its own branch, which is not on `main` yet — checked against `origin/main`
that legitimate case would fail, and the guard would need an exemption for refs the current diff
introduces. Against `HEAD` both cases fall out for free:

| Case | `--is-ancestor <ref> HEAD` | Correct? |
|---|---|---|
| In-flight stamp on its own PR branch (F-063 at PR time) | passes | yes |
| Landed feature, checked on `main` | passes | yes |
| Ref on an unmerged sibling branch (F-040) | **fails** | yes |
| Reflog-only orphan after a rebase (F-063 pre-repoint) | **fails** | yes |

Shallow clones must downgrade exactly as `_is_shallow_clone()` already makes the resolvability
check downgrade — an ancestry check on truncated history is noise, and this repository has
already learned that reporting benign absence as rot trains readers to ignore findings.

### Tasks

- [ ] Confirm the rule's cost before adopting it: run it over all 61 refs. **Already run at
      `d7deacf` — exactly 1 fails.** Re-run at implementation time; a different count means
      re-scope.
- [ ] `_check_git_refs`: add the ancestry assertion, sharing the shallow-clone downgrade and the
      missing-git path with the existing check. Distinct message text — "does not resolve" and
      "is not in this branch's history" are different defects with different fixes.
- [ ] Correct F-040's `implemented_in` to `3e26747a7be62eb91c1ebac6985d916b32ab7cdc`, with the
      rebase recorded in `notes` rather than silently repointed.
- [ ] Tests: a ref on an unmerged branch fails; an in-flight ref on the current branch passes; a
      shallow clone downgrades to a warning; a landed ref passes. The first two are the ones that
      matter — the guard is worthless if it cannot tell them apart.
- [ ] Claim an F-ID at land (next free per `openspec/project.md:34`), with a validation script
      that constructs a throwaway repository and observes the guard firing, rather than asserting
      the code contains a call.

### Exit criteria

`validate.py --tier fast --strict-git` fails on a synthetic unmerged-branch ref and passes on
`main`; all 61 refs are ancestors of `HEAD`.

### Why first

It is the cheapest item on the list, it closes a hole that has produced two wrong records in two
days, and it protects the audit trail every other workstream's credibility rests on. WS-2 and
WS-3 will each stamp new `implemented_in` refs; the guard should exist before they do, not after.

---

## WS-2 — `prove-m8-execution` task 4 · *unblocked · larger than previously stated*

### Correction to the sibling plan

[`plans/scenario-eval-matrices/PLAN.md`](../scenario-eval-matrices/PLAN.md) calls task 4
"**Small**". That was wrong, and the correction changes the schedule rather than the wording.

Task 4 requires converting `PIPELINES` from a mapping of literal dicts into a mapping of zero-arg
factories, because a shared M8 pipeline that owns a stateful fixture (a `tmp_path` sink, a
recording client) cannot be a module-level literal without leaking state between cells. That
conversion has a measured blast radius:

**Five call sites read `PIPELINES` as a mapping of dicts and break on the conversion**, two of
them on protected paths:

| Site | Reads |
|---|---|
| `scripts/validations/F_053.py:134` | `mc.pipeline_kinds(PIPELINES)` |
| `scripts/validations/F_063.py:165-169` | iterates `.items()`, indexes `cfg["judge"]["params"]` |
| `tests/test_matrix_coverage.py:92,148` | `mc.pipeline_kinds(PIPELINES)` |
| `tests/_matrix_coverage.py:1026` | `pipeline_kinds(PIPELINES)` inside `render_doc()` |
| `tests/test_matrix_eval_tools.py` | `_run()` deep-copies the literal |

### The stated precondition is now discharged

`openspec/changes/prove-m8-execution/tasks.md` requires, *before* the factory conversion:
"confirm no AST path reads `PIPELINES` as a literal (the extractor supports single-file constant
folding only)".

**Confirmed clear at `d7deacf`.** `scripts/extract_registries.py` calls `ast.parse` at lines 55
and 119 but never references `test_matrix_eval_tools`; every consumer of `PIPELINES` imports it
and reads it at runtime. The factory conversion is a runtime refactor over five known call sites,
not an AST problem. Recording this here so the next implementer does not re-derive it.

### Tasks

- [ ] Generalise `_run`'s tmp-path override into a table keyed by `(kind, type)` — currently
      `json_file`-only.
- [ ] Convert `PIPELINES` values to zero-arg factories; update the five call sites above in the
      same change (they cannot be split — two are protected paths and the conversion is atomic).
- [ ] Add the 19 pipelines, cheapest first, per the ordering already in
      `prove-m8-execution/tasks.md` §4.
- [ ] Regenerate `docs/matrix-coverage.md`; `M8_WAIVED` should be empty of anything a new cell now
      satisfies — the stale-waiver guard enforces this, so it will fail loudly rather than rot.

### Exit criteria

39 of 41 components execution-credited; `bedrock` and `phoenix_evals` remain waived with their
existing named reasons; `prove-m8-execution` is fully implemented and archivable.

### Why second, not third

13 new scorers arrive with WS-3. Landing them on a matrix that credits 20 of 41 means the first
question about any new number is "is this cell real?" — which is the question this whole change
exists to retire. Doing it after WS-3 means doing it on a larger surface.

---

## WS-3 — `add-testgen-eval-matrix` · *unblocked · the only scenario matrix that is*

Ships four deterministic scorers over AI-generated test suites: executability, mutation score in
both denominators, false alarms on correct code, obligation recall. Synthetic corpus, allowlisted
callable target, scorers as pure readers of its evidence.

**It ships no judge.** That is the reason it is here and the other two are not: nothing in it
queues behind B2. Its two dependencies — `add-gate-decision-provenance` (F-062) and
`prove-m8-execution` — are respectively landed and finished at WS-2.

- [ ] Corpus generator: control-flow templates, seeded non-equivalent mutants, gold obligations.
- [ ] Allowlisted execution target; scorers read its evidence and execute nothing themselves.
- [ ] Four scorers, advisory gate rules only until a soak exists — this is exactly what F-062's
      `report_only` was built for, and WS-3 is its first real consumer.
- [ ] Begin the soak. **The soak is the deliverable, not the scorers.** A single run is an
      anecdote; a distribution over held-out items is a result.

### Exit criteria

Four scorers green in the matrix at the required dimensions; a soak running with every new rule
`report_only`; one exported artifact carrying a `GateDecision` a later run can be diffed against.

---

## Not next, and why

| Candidate | Status | Gate |
|---|---|---|
| `add-rca-eval-matrix` | Proposed, 29 tasks | **B1.** Synthetic-only is shippable now, but shipping it before B1 is decided means building the corpus twice if the answer is "real telemetry" |
| `add-requirements-gen-eval-matrix` | Proposed, 29 tasks | Sequenced after WS-3; its provenance-capture half is independent of B2 and could be pulled forward if WS-3 slips |
| `add-measurement-harness-wedge` | Proposed, 44 tasks | CHARTER §3 amendment + GOVERNANCE sign-off, secret rotation, package rename over third-party marks. **Zero of the blockers are engineering** |
| `add-production-eval-flywheel` | Blocked | CHARTER §3 ratified amendment plus its own ADR |
| `extend-judge-calibration`, `add-repeat-reliability-metrics` | Implemented, pending archive | Archive them when their `spec-guardian` / `peer-reviewer` passes run |

The measurement wedge deserves a note rather than silence. Its premise — "the system has strong
internal validation and no external evidence" — is still true, and WS-2 and WS-3 both add
internal validation. That is the right call while the wedge's human blockers are open, and it
stops being the right call the moment they close. It should be re-ranked at every decision gate,
not left to drift down the list because it is inconvenient.

---

## Decisions needed from a human, with consequences

These are the same B1–B3 as the sibling plan, restated with what they now gate.

| # | Decision | Gates | Cost of no answer |
|---|---|---|---|
| B1 | Real incident telemetry under a CHARTER §3 ratified amendment with deterministic redaction, or synthetic-only permanently | WS-4 (`add-rca-eval-matrix`) | The RCA corpus gets built twice, or gets built wrong |
| B2 | Who produces ~200–350 paired `HUMAN_AUDIT` labels per judged scorer, and by when | Every judge-backed scorer, forever | "Calibrated judge" stays a capability that is owned and never switched on |
| B3 | A CODEOWNER turnaround target under single-maintainer branch protection (ADR 0037) | Every workstream here — all touch protected paths | Any schedule in this document is a hope, not a date |

**B3 is the dominant term.** WS-1, WS-2 and WS-3 each need the `eval-change-approved` label plus
CODEOWNER review. The coding is not the long pole and has not been for some time.

---

## Sequencing summary

```
WS-1  provenance ancestry guard      unblocked   ~1 day     do first
WS-2  prove-m8-execution task 4      unblocked   larger than previously stated
WS-3  add-testgen-eval-matrix        unblocked   the soak is the deliverable
----- decision gate: B1, B2, B3 ------------------------------------------------
WS-4  add-rca-eval-matrix            needs B1
WS-5  add-requirements-gen-matrix    sequenced after WS-3
WS-6  add-measurement-harness-wedge  needs governance, not engineering
```

Each workstream is one PR against a protected path. None of them may be batched to save review
rounds: `scripts/eval_protected_paths.py` exists so that a widening of what a metric *means* gets
looked at on its own.

---

## Verification

Every claim of "done" in this plan is checked by commands that already exist:

```bash
./scripts/quality-gate.sh all
python scripts/validate.py --tier fast --strict-git
python tests/test_matrix_coverage.py --check
python -m pytest tests/ --cov=src/eval_harness --cov-branch    # 96% floor
make pre-pr
```

---

## Related documents

- [`plans/eval-evidence-integrity/PLAN.md`](../eval-evidence-integrity/PLAN.md) — owns M8 semantics
- [`plans/scenario-eval-matrices/PLAN.md`](../scenario-eval-matrices/PLAN.md) — owns the VP narrative
- [`plans/scenario-eval-matrices/REVIEW.md`](../scenario-eval-matrices/REVIEW.md) — the two-pass peer review
- [`openspec/README.md`](../../../openspec/README.md) — the change index
- [`NEXT_STEPS.md`](../../../NEXT_STEPS.md) — ledger of landed work

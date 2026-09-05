# Implementation Plan — Eval Delivery Sequencing

**ID:** PLAN-2026-09-05-eval-delivery-sequencing
**Date:** 2026-09-05 · **Revision 2** · **Base commit:** `d7deacf`
**Motivated by:** F-062 and F-063 landing (PRs #181, #182), which cleared the two prerequisites the
three scenario-eval matrices were queued behind — and by a provenance defect found while verifying
F-063's own `implemented_in` ref.
**Reviewed by:** [`./REVIEW.md`](REVIEW.md) — eleven findings against revision 1, six of which
changed this document and two of which changed its recommendations.
**Scope:** decide what the eval workstream does next, in what order, and which steps are blocked on
a human rather than on engineering. Ordering, sizing and gating only.
**Non-goals:** restating the plans that already own their workstreams (see *Ownership*); designing
the three scenario matrices; any change to a gate's semantics.

> Not [`NEXT_STEPS.md`](../../../NEXT_STEPS.md) at the repository root, which is a ledger of landed
> work and named deferrals. This document is forward-looking and sequencing-only.

---

## The uncomfortable part, first

**Revision 1 of this plan sized four workstreams by counting checkboxes in their `tasks.md`, and
never asked whether the checkboxes were true. For one of them they were not.**
`add-measurement-harness-wedge` reads 44-open / 0-done; its WS-0 shipped weeks ago as **F-048**
(`features.yaml:831-837`, `.gitleaks.toml`, the fail-closed scan at `quality-gates.yml:274`). That
is crediting a *declaration* instead of an *execution* — the exact defect the last three PRs
removed from the M8 matrix — reintroduced at the planning layer by the person who removed it.

Sizing in this revision is derived from `features.yaml` F-IDs and CI evidence. Checkbox counts are
treated as a **lower bound on progress**, never as a measure of remaining work.

**Second:** three of the four candidate workstreams are blocked on decisions no engineer can make.
`add-rca-eval-matrix` needs B1 settled or it stays synthetic forever. Every judge-backed scorer
needs B2 or it is advisory forever. The wedge's remaining phases need a CHARTER §3 ratified
amendment, a package rename over third-party marks, and a rotation confirmation. What is genuinely
unblocked is narrow: WS-1, WS-2, and `add-testgen-eval-matrix` — which ships no judge precisely so
it would not queue behind calibration.

**Third:** the feature registry's core claim is unverified. 61 features assert
`implemented_in: <sha>`; the check proves those SHAs are *commits*, not that they are *in main*.
One is not.

---

## Cost is denominated in review rounds, not days

Every workstream below touches a protected path and needs the `eval-change-approved` label plus
CODEOWNER review under single-maintainer branch protection (ADR 0037). A one-day change and a
two-week change cost **the same review round**. Revision 1 asserted that review latency dominates
and then ordered by engineering effort anyway; this revision prices everything in the unit that is
actually scarce.

| Unit | Meaning |
|---|---|
| **1 round** | One PR, one label request, one CODEOWNER pass, one CI cycle |
| **Engineering** | Rough implementation effort, secondary — it does not set the schedule |

On batching: nothing enforces one-change-per-PR. `scripts/eval_protected_paths.py` exports a path
set and requires a labelled review for any PR that touches it; a PR touching all three workstreams
would satisfy it exactly once. Revision 1 cited that script as if it forbade batching. It does not.
Keeping them separate is a **judgement**: WS-2 rewrites how the M8 corpus is constructed and WS-3
adds four scorers that will be read *through* that corpus, so reviewing them together means
reviewing a metric's meaning and its first results in one pass. That is the review this repository's
protected-path rule exists to make possible, and batching would collapse it. WS-1 is small enough
that batching it with WS-2 is defensible if review capacity is the binding constraint — offered as
an option below, not taken unilaterally.

---

## Ownership — what this plan does not own

| Workstream | Owner document | This plan's role |
|---|---|---|
| M8 semantics, enforcement-before-evidence, the 41-component widening | [`plans/eval-evidence-integrity/PLAN.md`](../eval-evidence-integrity/PLAN.md) | Order it, size it, discharge its precondition, and challenge one of its design choices (WS-2 D1) |
| VP narrative, decks, the three-scenario story, blockers B1–B4 | [`plans/scenario-eval-matrices/PLAN.md`](../scenario-eval-matrices/PLAN.md) | Correct two claims in it; do not restate it |
| Per-change design and tasks | `openspec/changes/<id>/` | Reference; never duplicate |

An entry here that contradicts an owner document is a defect in this document, not a decision.

---

## Current state, measured at `d7deacf`

Executed against this checkout, not recalled.

### M8 composability — 20 of 41 credited, 2 waived, 19 outstanding

The 19 are **not equal work**. Three already execute in the suite and need only an entry so the
matrix's ledger agrees with reality:

| Class | Components | Work |
|---|---|---|
| **Accounting move** — already executes elsewhere | `csv` (`tests/integration/test_pipeline_e2e.py:110`), `parquet`, `langfuse` sink (`tests/test_engine.py:36`) | Add to `PIPELINES`; no new test construction |
| **New cell, zero-config stand-in exists** | `braintrust`/`phoenix` sinks (`Null*` clients), `braintrust`/`langfuse` datasets, `panel` judge over `mock` members, `html_file`, `jsonl` | Build the pipeline |
| **New cell, needs a fixture or resource** | `sqlite` (`:memory:`), `filesystem` (tmp root), `mock_http`, `model` target | Build the pipeline **and** resolve D1 below |
| **New cell, scorers** | `autoevals`, `json_keys`, `policy_violation`, `regex_match`, `state_transition` | Build the pipeline |
| **Waived, reasons intact** | `bedrock`, `phoenix_evals` | None |

### Change-package state, derived from `features.yaml` and CI

| Change | Checkbox ledger | What the repository says | Trust |
|---|---|---|---|
| `add-gate-decision-provenance` | — | **Landed, F-062** (`features.yaml:1171`) | Index text stale, fixed in this PR |
| `prove-m8-execution` | 17 done / 6 open | Tasks 1-3, 5 landed (F-063); task 4 outstanding | Accurate |
| `extend-judge-calibration` | 20 / 0 | Implemented, pending archive | Accurate |
| `add-repeat-reliability-metrics` | 37 / 0 | Implemented, pending archive | Accurate |
| `add-measurement-harness-wedge` | 44 open / **0 done** | **WS-0 landed as F-048**; WS-1–WS-5 open | **Stale — see R1** |
| `add-testgen-eval-matrix` | 30 open | Genuinely new | Accurate |
| `add-rca-eval-matrix` | 29 open | Genuinely new | Accurate |
| `add-requirements-gen-eval-matrix` | 29 open | Genuinely new | Accurate |

### Provenance

61 `implemented_in` refs. All 61 resolve. **60 are ancestors of `HEAD`; one is not.**

---

## WS-1 — Provenance ancestry guard · **1 round** · small · *do first*

### The gap, stated precisely

`scripts/validate.py:235` verifies a ref with `git rev-parse --verify --quiet "<ref>^{commit}"` —
*"is this a commit?"*, not *"did it land?"*. CI runs `--strict-git` (`quality-gates.yml:172`) with
`fetch-depth: 0`, which fetches every branch, so a commit on an **unmerged** branch resolves there.

Revision 1 called this "the same failure mode" as F-063's orphaned SHA. It is not, and the true
version is the stronger argument:

| | F-063 (pre-repoint) | F-040 (today) |
|---|---|---|
| Where the object lived | local reflog only, after a rebase | `origin/feat/F-040-soak-stats` |
| Fresh CI clone, `fetch-depth: 0` | **absent** → `rev-parse` fails | **present** → resolves |
| Existing `--strict-git` | would have caught it | passes, and has for six weeks |

The existing guard is a working backstop for unreachable objects. It has no answer for **reachable
but never landed**, and the repository's only defence against that is a convention in a YAML
comment (`quality-gates.yml:171`: *"Squash-merging a PR would rot its own ref, so keep merge
commits"*). A convention is not a guard.

### The instance

`F-040` records `implemented_in: 0f19ecaa8…`, which exists only on
`origin/feat/F-040-soak-stats`. The feature landed via PR #113 from
`feat/F-040-soak-stats-**rebased**` as `3e26747a7be62eb91c1ebac6985d916b32ab7cdc`. `status: done` is
correct; the pointer is stale.

### The fix, and why it needs no exemption list

Add `git merge-base --is-ancestor "<ref>" HEAD` beside the existing resolvability check. `HEAD`
rather than `origin/main` is load-bearing, and the choice was checked against the real CI shape
(REVIEW R10): `quality-gates.yml` triggers on `pull_request` and `push: [main]` with default
`actions/checkout` and `fetch-depth: 0`, so on a PR `HEAD` is the detached merge commit whose
parents are base and PR head.

| Case | Result | Correct? |
|---|---|---|
| In-flight stamp on its own PR branch (F-063 at PR time) | passes | yes |
| Landed feature, checked on `main` | passes | yes |
| Ref on an unmerged sibling branch (F-040) | **fails** | yes |
| Reflog-only orphan after a rebase | **fails** | yes |

Shallow clones must downgrade exactly as `_is_shallow_clone()` already makes the resolvability check
downgrade — this repository has already learned that reporting benign absence as rot trains readers
to ignore findings.

### Tasks

- [ ] Re-run the rule over all 61 refs before adopting it. **At `d7deacf` exactly 1 fails**; a
      different count at implementation time means re-scope, not override.
- [ ] `_check_git_refs`: add the ancestry assertion, sharing the shallow-clone downgrade and the
      missing-git path. Distinct message text — "does not resolve" and "is not in this branch's
      history" are different defects with different fixes.
- [ ] Correct F-040's `implemented_in` to `3e26747a7be62eb91c1ebac6985d916b32ab7cdc`, recording the
      rebase in `notes` rather than silently repointing.
- [ ] Tests: unmerged-branch ref fails; in-flight ref on the current branch passes; shallow clone
      downgrades; landed ref passes. The first two are the ones that matter.
- [ ] Claim an F-ID at land, with a validation script that constructs a throwaway repository and
      **observes the guard firing**, rather than asserting the code contains a call.

**Exit:** `validate.py --tier fast --strict-git` fails on a synthetic unmerged-branch ref, passes on
`main`, and all 61 refs are ancestors of `HEAD`.

**Why first:** it is one round, it protects the audit trail every other workstream's credibility
rests on, and WS-2 and WS-3 will each stamp new refs. The guard should exist before they do.

---

## WS-2 — `prove-m8-execution` task 4 · **1 round** · the sprint's largest engineering item

### Correction carried into the sibling plan

[`plans/scenario-eval-matrices/PLAN.md`](../scenario-eval-matrices/PLAN.md) called task 4
"**Small**". It is not: 19 cells is the bulk of the work. But revision 1 of *this* plan then
overstated the refactor risk in the other direction, and both corrections are recorded rather than
quietly swapped.

### D1 — the decision this plan exists to surface: are factories needed at all?

`prove-m8-execution/tasks.md` §4 requires `PIPELINES` values to become zero-arg factories. Revision 1
accepted that and priced its consequences. The question it should have asked is what the factories
buy.

**Deep-copy isolation already works for a live, stateful, recording object in a module-level
literal.** Verified: after both judge M8 tests run in one session,
`PIPELINES["openai_judge"]["judge"]["params"]["client"].calls == 0`. `_run` deep-copies before
validating; each test asserts against its own copy. That is the state leak factories are usually
introduced to prevent, already solved.

Two cases genuinely resist a literal:

1. **A value from `tmp_path`** — for which §4's own first bullet is the non-factory answer:
   generalise `_run`'s tmp-path override into a table keyed by `(kind, type)`.
2. **A value from a pytest fixture** — `NullLangfuseClient(dataset_items=...)`, `fake_braintrust`
   (`tests/conftest.py:79-119`). A function-scoped fixture cannot be read at module import.

**Recommendation: the hybrid.** Literals stay literals; only fixture-dependent entries become
callables; `pipeline_kinds` tolerates both. Cost — corrected from revision 1's five breakages:

| Site | Reads | Change |
|---|---|---|
| `tests/_matrix_coverage.py:763-790` `pipeline_kinds` | one `pipelines.values()` loop | `cfg() if callable(cfg) else cfg` — **fixes three consumers at once** |
| `scripts/validations/F_063.py:165-169` | indexes `cfg["judge"]["params"]` | structural, must change |
| `tests/test_matrix_eval_tools.py::_run` | deep-copies the literal | structural, must change |
| `F_053.py:134`, `test_matrix_coverage.py:92,148`, `_matrix_coverage.py:1026` | all via `pipeline_kinds` | **no change** |

Three edits, two structural. The cost of the hybrid is a mixed-type mapping — uglier, and it needs a
typed alias to stay legible. **That trade belongs to the change owner; this plan's job was to
surface it.** If the owner prefers the whole-dict conversion for uniformity, the cost is the same
three edits plus every literal rewritten, and it should be chosen for that reason rather than
inherited from the proposal unexamined.

### The stated precondition is discharged

`tasks.md` §4 requires, before any conversion: *"confirm no AST path reads `PIPELINES` as a
literal"*. **Confirmed clear at `d7deacf`** — `scripts/extract_registries.py` calls `ast.parse` at
lines 55 and 119 but never references `test_matrix_eval_tools`; every consumer imports and reads at
runtime. Recorded so the next implementer does not re-derive it.

### Tasks

- [ ] **Settle D1 first.** Everything below is cheaper under the hybrid.
- [ ] Generalise `_run`'s tmp-path override into a `(kind, type)` table — currently `json_file`-only.
- [ ] Land the three accounting moves (`csv`, `parquet`, `langfuse` sink) before any new cell: they
      are the cheapest possible proof the mechanism still works after D1.
- [ ] Add the remaining 16 cells, cheapest first, per `prove-m8-execution/tasks.md` §4.
- [ ] Regenerate `docs/matrix-coverage.md`. The stale-waiver guard will fail loudly if a new cell
      satisfies a waiver, which is the intended behaviour.

**Exit:** 39 of 41 components execution-credited; `bedrock` and `phoenix_evals` still waived with
their existing reasons; `prove-m8-execution` fully implemented and archivable.

**Why second:** 13 new scorers arrive with WS-3. Landing them on a matrix that credits 20 of 41
means the first question about any new number is "is this cell real?" — the question this change
exists to retire.

---

## WS-3 — `add-testgen-eval-matrix` · **1 round + a soak** · the only unblocked scenario matrix

Four deterministic scorers over AI-generated test suites: executability, mutation score in both
denominators, false alarms on correct code, obligation recall. Synthetic corpus, allowlisted
callable target, scorers as pure readers of its evidence.

**It ships no judge** — verified in its own proposal (*"Non-goal: a judge. Every scorer here is
decidable by execution... `require_calibration_for_judge_gating` is not engaged at all"*). That is
why it is here and the other two are not: nothing in it queues behind B2. Its dependencies —
`add-gate-decision-provenance` (landed, F-062) and `prove-m8-execution` (finished at WS-2) — are
both satisfied by the time it starts.

- [ ] Corpus generator: control-flow templates, seeded non-equivalent mutants, gold obligations.
- [ ] Allowlisted execution target; scorers read its evidence and execute nothing themselves.
- [ ] Four scorers, advisory gate rules only until a soak exists. This is F-062's `report_only`
      first real consumer.
- [ ] Begin the soak. **The soak is the deliverable, not the scorers.** One run is an anecdote; a
      distribution over held-out items is a result.

**Exit:** four scorers green at the required dimensions; a soak running with every new rule
`report_only`; one exported artifact carrying a `GateDecision` a later run can be diffed against.

---

## Not next, and why

| Candidate | True state | Gate |
|---|---|---|
| `add-rca-eval-matrix` | New, 29 tasks | **B1.** Synthetic-only ships today, but building it before B1 is decided risks building the corpus twice |
| `add-requirements-gen-eval-matrix` | New, 29 tasks | After WS-3; its provenance-capture half is independent of B2 and can be pulled forward if WS-3 slips |
| `add-measurement-harness-wedge` | **WS-0 landed (F-048)**; WS-1–WS-5 open | CHARTER §3 amendment + GOVERNANCE sign-off, rotation confirmation, package rename over third-party marks. The remaining blockers are governance — **but that was not true of WS-0, and revision 1 said it was** |
| `add-production-eval-flywheel` | Blocked | CHARTER §3 ratified amendment plus its own ADR |
| `extend-judge-calibration`, `add-repeat-reliability-metrics` | Implemented | Archive when their `spec-guardian` / `peer-reviewer` passes run. **Cheap, and they are the two most misleading entries in the index while they sit "pending"** |

The wedge deserves a standing note rather than silence. Its premise — *"the system has strong
internal validation and no external evidence"* — remains true, and WS-2 and WS-3 both add internal
validation. That is the right call while its human blockers are open, and it stops being the right
call the moment they close. Re-rank it at every decision gate; do not let it drift down the list
because it is inconvenient, and do not size it from its checkbox ledger again.

---

## Decisions needed from a human

| # | Decision | Gates | Cost of no answer |
|---|---|---|---|
| B1 | Real incident telemetry under a CHARTER §3 ratified amendment with deterministic redaction, or synthetic-only permanently | `add-rca-eval-matrix` | The RCA corpus gets built twice, or gets built wrong |
| B2 | Who produces ~200–350 paired `HUMAN_AUDIT` labels per judged scorer, and by when | Every judge-backed scorer, forever | "Calibrated judge" stays a capability that is owned and never switched on |
| B3 | A CODEOWNER turnaround target under single-maintainer branch protection (ADR 0037) | Every workstream here | Any schedule in this document is a hope, not a date |
| D1 | Hybrid vs. whole-dict `PIPELINES` conversion (WS-2) | WS-2's shape | The conversion gets inherited from the proposal unexamined |

**B3 is the dominant term.** Three rounds is the floor for WS-1 → WS-3, and the coding is not the
long pole.

---

## Sequencing summary

```
WS-1  provenance ancestry guard      1 round   small        do first
WS-2  prove-m8-execution task 4      1 round   large        settle D1 first
WS-3  add-testgen-eval-matrix        1 round   large        the soak is the deliverable
----- decision gate: B1, B2, B3 ------------------------------------------------
WS-4  add-rca-eval-matrix            needs B1
WS-5  add-requirements-gen-matrix    after WS-3
WS-6  add-measurement-harness-wedge  WS-0 done; the rest needs governance
```

**Floor: 3 review rounds.** WS-1 may be batched into WS-2's round if review capacity binds; WS-2 and
WS-3 should not be batched, for the reason given above.

---

## What would make this plan wrong

Stated so a reader in three weeks can check it rather than re-derive it.

| If this turns out to be true | Then |
|---|---|
| B3 comes back as "one round per week or worse" | Batch WS-1 into WS-2 immediately, and reconsider whether WS-3's soak can start before its scorers are fully reviewed |
| D1 resolves to whole-dict conversion | WS-2 grows by every literal rewritten; it stops being co-schedulable with anything |
| B2 gets funded | `extend-judge-calibration` jumps ahead of WS-3 — a calibrated judge unblocks two matrices, testgen unblocks one |
| B1 resolves to "real telemetry" | WS-4 acquires a redaction workstream and stops being a one-round change |
| The wedge's governance blockers clear | It outranks WS-5 immediately; it is the only item here that produces *external* evidence |
| Another `implemented_in` ref fails the ancestry rule at implementation time | WS-1 is a data-cleanup change first and a guard second; re-scope rather than force the guard through |

---

## Verification

```bash
./scripts/quality-gate.sh all
python scripts/validate.py --tier fast --strict-git
python tests/test_matrix_coverage.py --check
python -m pytest tests/ --cov=src/eval_harness --cov-branch    # 96% floor
make pre-pr
```

---

## Related documents

- [`./REVIEW.md`](REVIEW.md) — the peer review that produced this revision
- [`plans/eval-evidence-integrity/PLAN.md`](../eval-evidence-integrity/PLAN.md) — owns M8 semantics
- [`plans/scenario-eval-matrices/PLAN.md`](../scenario-eval-matrices/PLAN.md) — owns the VP narrative
- [`plans/scenario-eval-matrices/REVIEW.md`](../scenario-eval-matrices/REVIEW.md) — the two-pass peer review
- [`openspec/README.md`](../../../openspec/README.md) — the change index
- [`NEXT_STEPS.md`](../../../NEXT_STEPS.md) — ledger of landed work

# Review — Eval Delivery Sequencing (PLAN.md)

**Reviewed:** `docs/plans/eval-delivery-sequencing/PLAN.md` at `7047989`, one day old, written by the
same author. **Base commit:** `d7deacf`. Every claim below was executed against this checkout.

## Verdict

The plan's ordering survives. Its **evidence does not**, in three places, and one of the failures is
the exact defect the surrounding work exists to remove: **it sized four workstreams by counting
checkboxes and never asked whether the checkboxes were true.** For one change they were not.

Six findings change what the plan says. Two change what it recommends. One (R10) is a claim that
held up under attack and is recorded as such, so that a reader can tell a checked claim from an
unchecked one.

---

## R1 — The sizing metric was never validated, and it is wrong for the change ranked last

**Severity: high. The plan's ranking depends on it.**

PLAN.md sized four OpenSpec packages by counting `- [ ]` and `- [x]` in their `tasks.md`, reporting
"measurement-wedge 44 · testgen 30 · rca 29 · requirements-gen 29. All are 0-done."

`add-measurement-harness-wedge`'s **WS-0 has landed.** Its own proposal
(`openspec/changes/add-measurement-harness-wedge/proposal.md:80`) says "next free today: **F-048**".
`features.yaml:831-837` carries **F-048 — "Credential scrub + fail-closed secret-scan gate
(gitleaks)" — `status: done`**. `.gitleaks.toml` is committed and `quality-gates.yml:274` runs a
fail-closed secret scan. That is WS-0's entire description ("Redact the still-live Langfuse key
pair from three tracked files, land a fail-closed gitleaks gate"), shipped.

The checkbox ledger says 0 done. The repository says otherwise.

This is the same defect class the last three PRs removed — crediting a **declaration** instead of an
**execution** — reintroduced one layer up, at the planning layer, by the author who removed it.
A checkbox in a proposal is a claim about work; `features.yaml` and CI are the evidence.

Checkbox accuracy is not uniformly bad, which is what makes it dangerous: `extend-judge-calibration`
(20/20) and `add-repeat-reliability-metrics` (37/37) are accurate, and `prove-m8-execution` (17/6) is
accurate because it was hand-corrected two days ago. The metric is right often enough to look
trustworthy.

**Correction:** size against `features.yaml` F-IDs and CI evidence, and treat checkbox counts as a
lower bound on progress, never as a measure of remaining work.

## R2 — "Zero of the blockers are engineering" was false in both directions

PLAN.md ranked the wedge last with: *"CHARTER §3 amendment + GOVERNANCE sign-off, secret rotation,
package rename over third-party marks. **Zero of the blockers are engineering.**"*

WS-0 was engineering — a redaction sweep, a gitleaks gate, and a `SECURITY.md` correction — and it
is done. The sentence was wrong when written and would have been wrong in the other direction a
month earlier.

The *conclusion* (rank it after the unblocked work) survives; the *reason* given for it does not.
A ranking defended by a false reason is one good question away from being reversed for the wrong
cause.

## R3 — WS-2's blast radius was overstated by more than 2×

PLAN.md: *"Five call sites read `PIPELINES` as a mapping of dicts and break on the conversion, two of
them on protected paths"*, then tabulated five.

Three of the five do not read `PIPELINES` structurally at all — they pass it to
`mc.pipeline_kinds()`:

| Site | What it actually does | Breaks? |
|---|---|---|
| `scripts/validations/F_053.py:134` | `mc.pipeline_kinds(PIPELINES)` | no |
| `tests/test_matrix_coverage.py:92,148` | `mc.pipeline_kinds(PIPELINES)` | no |
| `tests/_matrix_coverage.py:1026` | `pipeline_kinds(PIPELINES)` | no |
| `scripts/validations/F_063.py:165-169` | iterates `.items()`, indexes `cfg["judge"]["params"]` | **yes** |
| `tests/test_matrix_eval_tools.py::_run` | deep-copies the literal | **yes** |

`pipeline_kinds` (`tests/_matrix_coverage.py:763-790`) has exactly one `for config_dict in
pipelines.values()` loop. Teaching it `cfg() if callable(cfg) else cfg` fixes all three consumers at
once. Real cost: **three edits, two of them structural**, not five breakages.

I listed sites that *mention* `PIPELINES` without checking whether they *destructure* it.

## R4 — And the conversion those edits pay for may not be needed

**Severity: high. This is the finding that most changes the work.**

`prove-m8-execution/tasks.md` §4 requires `PIPELINES` values to become zero-arg factories. PLAN.md
accepted that as given and priced its consequences. It should have asked what the factories buy.

**Deep-copy isolation already works for a live, stateful, recording object held in a module-level
literal.** Verified: after `test_m8_pipeline_with_openai_judge_and_injected_client` and its
`anthropic` sibling both run in one session,

```
PIPELINES["openai_judge"]["judge"]["params"]["client"].calls == 0
```

The module-level fixture stays pristine because `_run` deep-copies before validating, and each test
asserts against its own copy. That is precisely the state-leak factories are usually introduced to
prevent, already solved.

Two cases genuinely resist a literal, and only two:

1. **A value that must come from a `tmp_path`** — for which §4's *own first bullet* is the
   non-factory answer: generalise `_run`'s tmp-path override into a table keyed by `(kind, type)`.
   The change already contains the fix and then also converts everything.
2. **A value that must come from a pytest fixture** — `NullLangfuseClient(dataset_items=...)`, the
   `fake_braintrust` fixture at `tests/conftest.py:79-119`. A function-scoped fixture cannot be read
   at module import, full stop.

So the honest scope is a **hybrid**: literals stay literals; only fixture-dependent entries become
callables, and `pipeline_kinds` tolerates both. That confines the change to the three edits in R3
instead of a whole-dict rewrite, and it leaves the 19 cells — which are the actual work — untouched
by refactor risk.

The cost of the hybrid is a mixed-type mapping, which is uglier and needs a typed alias to stay
legible. That trade is the change owner's to make; the plan's job was to surface it, and it did not.

## R5 — A policy was attributed to a script that does not implement it

PLAN.md: *"None of them may be batched to save review rounds: `scripts/eval_protected_paths.py`
exists so that a widening of what a metric means gets looked at on its own."*

`scripts/eval_protected_paths.py` exports `PROTECTED_PATTERNS` — a path set consumed by the CI
guard, the disabled auto-fix loop's scope guard, and the tests. It requires the
`eval-change-approved` label plus CODEOWNER review for a *touching* PR. **It says nothing about
batching**, and a single PR touching all of WS-1, WS-2 and WS-3 would satisfy it exactly once.

Keeping the changes separate is a defensible judgement about reviewability. Presenting it as an
existing enforced rule is not, and it is the kind of citation that survives into a document nobody
re-checks.

## R6 — The F-063/F-040 comparison is wrong, and the true version is a stronger argument

PLAN.md: *"This is the same failure mode that orphaned F-063's SHA two days ago. That one was caught
by hand, this one was not caught for six weeks."*

They are different failure modes, and the difference is the whole point:

| | F-063 (pre-repoint) | F-040 (today) |
|---|---|---|
| Where the object lived | local reflog only, after a rebase | `origin/feat/F-040-soak-stats`, a real remote branch |
| Fresh CI clone, `fetch-depth: 0` | object **absent** → `rev-parse --verify` fails | object **present** → resolves cleanly |
| Existing `--strict-git` | **would have caught it** | passes, and has for six weeks |

The existing guard was a working backstop for F-063; I caught that one by hand before CI got the
chance. It has no answer at all for F-040. So the gap is not "orphaned refs" generally — it is
specifically **"reachable but never landed"**, and the repository's only defence against it is a
convention in a YAML comment (`quality-gates.yml:171`, *"Squash-merging a PR would rot its own ref,
so keep merge commits"*).

Narrower than the plan claimed, and less defended. WS-1's justification improves when stated
correctly.

## R7 — Cost is denominated in the wrong unit

The plan asserts B3 (protected-path review latency under single-maintainer branch protection) is
"the dominant term, not the coding", and then orders the work by engineering effort and prices
exactly one item, in days ("~1 day").

If review rounds are the scarce resource, every workstream needs a review-round count and the
ordering must be defended in that unit. A one-day change and a two-week change cost the *same*
review round; that fact should drive batching decisions (see R5) rather than being stated and
then ignored.

## R8 — `openspec/README.md` is stale in two places, and its CI guard cannot detect it

- `openspec/README.md:57-63` — `add-gate-decision-provenance`: "***proposed***". It landed as
  **F-062** (`features.yaml:1171`), two days ago, by me.
- `openspec/README.md:41-45` — `add-measurement-harness-wedge`: "***proposed***". Its WS-0 landed as
  F-048 (R1).

The *OpenSpec change index* guard in `.github/workflows/docs.yml` asserts that every directory under
`changes/` appears in the README and that no archived one does. It checks **presence, not truth** —
the status word beside each entry is unguarded prose.

Same shape as the `implemented_in` finding WS-1 exists to fix: the cheap property is enforced, the
meaningful one is not. Worth naming as a pattern rather than as two unrelated typos.

## R9 — The 19 outstanding M8 components are not equal work

PLAN.md tabulates 19 uncredited components as one flat list. `prove-m8-execution/tasks.md` §4 already
distinguishes a subset, and it is right to:

- `csv` executes today at `tests/integration/test_pipeline_e2e.py:110`
- the `langfuse` sink executes today at `tests/test_engine.py:36`
- `parquet` likewise runs outside `PIPELINES`

For those three, crediting them is an **accounting move** — adding an entry so the matrix's own
ledger agrees with the suite — not new test construction. A flat 19 overstates the build.

## R10 — WS-1's `HEAD` choice survives the CI checkout *(claim upheld)*

Recorded because a checked claim should be distinguishable from an unchecked one.

`quality-gates.yml` triggers on `pull_request` (types `[opened, synchronize, reopened, labeled,
unlabeled]`) and `push: branches: [main]`, checking out with default `ref` and `fetch-depth: 0`.
On a pull request that is a detached HEAD at the merge commit, whose parents are the base and the PR
head — so a SHA stamped on the PR branch **is** an ancestor of `HEAD`, and a SHA on an unrelated
unmerged branch is not. On a push to `main`, `HEAD` is `main`.

Both cases behave as the plan claimed, with no exemption list. The design holds.

## R11 — No falsification section

The plan states an order and defends it. It never says what evidence would make the order wrong —
which is the section that makes a plan re-readable in three weeks. Added in the rewrite.

---

## Disposition

| # | Finding | Action in the rewrite |
|---|---|---|
| R1 | Checkbox sizing unvalidated; wedge WS-0 landed as F-048 | Sizing re-derived from `features.yaml` + CI; the metric's failure recorded in-document |
| R2 | "Zero blockers are engineering" false | Ranking kept, reason replaced |
| R3 | Blast radius overstated 5 → 2 structural sites | Table corrected |
| R4 | Factory conversion may be unnecessary | Promoted to an explicit decision with a recommendation |
| R5 | Batching policy attributed to a script | Restated as a judgement, argued |
| R6 | F-063/F-040 conflated | Comparison table; WS-1's justification narrowed and strengthened |
| R7 | Wrong cost unit | Every workstream priced in review rounds |
| R8 | `openspec/README` stale ×2, guard checks presence not truth | Both corrected in this PR; the pattern named |
| R9 | 19 components treated as equal | Split into accounting moves vs. new cells |
| R10 | `HEAD` choice | Upheld, marked as verified |
| R11 | No falsification criteria | Section added |

## Method and limitations

Every claim was re-derived by execution against `d7deacf` — registry census, ancestry over all 61
`implemented_in` refs, a live pytest run to observe deep-copy isolation, and direct reads of the
cited lines. No claim in the rewrite is carried over from the first draft on trust.

**Not checked:** whether the three scenario-matrix packages' task lists are internally accurate
(they are new and 0-done, so R1's failure mode cannot yet apply to them); whether `bedrock` and
`phoenix_evals` waivers remain justified; anything about the `flow-corpus` or `agent-core` suites.

# Review: add-testgen-eval-matrix

**Reviewed:** the externally supplied `add-testgen-eval-matrix` package, re-verified against
`28eb09d`. Full findings: `docs/plans/scenario-eval-matrices/REVIEW.md`.

## Verdict

The source package identified a real gap and the right extension point: the harness has no
test-artifact signal, and registry-registered scorers are the correct way to add one. Four defects
would have made it fail CI on first push, and a fifth would have sent the implementer down a dead
end.

The scope was also roughly three times what the evidence supports. Fourteen scorers were proposed;
four have oracles this corpus can actually provide.

## Corrections applied

| # | Finding | Correction |
|---|---|---|
| A10 | "Sandbox execution uses the `filesystem` and `sqlite` state adapters" | A `StateAdapter` is a snapshot/diff seam — `src/eval_harness/state_adapters/__init__.py:28-36` says it "does not intercept or observe the target's execution". Execution moved into an allowlisted callable target; scorers read `TargetOutput.metadata` |
| A9 | `testgen_flake_rate` registered as a scorer | `Scorer.score(item, output, ctx)` sees one attempt. Replaced with `repetitions: 5` + `metric: pass_power_k` on `test_executability` (F-056) |
| A8 | One 14-scorer module | `MAX_FILE_LINES = 500` is a hard gate; `trajectory.py` is 454 lines for 7. Cut to 4 scorers in a 3-file package |
| A7 | "Add MATRIX_KIND rows for all scorers" as one checkbox | Scorer floor is M1,M2,M3,M5,M6. 4 scorers = **20 cells**, enumerated in task 4.1, plus both baselines and both READMEs |
| A5 | No `openspec/README.md` index entry | Added as task 6.3. The guard matches `](target)`, so a change dir that is only named in prose fails `docs.yml` |
| A11/A16 | Corpus at `flow-corpus/test-generation/v1/` | Wrong path convention, wrong content charter, and on the wrong side of CHARTER §3. Moved to `corpora/testgen/v1/` and made synthetic |
| A13 | k=5, thresholds in requirement prose | No numeric literal in the spec delta. All four bounds live in `config/` as soak starting points |
| C2.d | "raw + normalized mutation score per Inozemtseva's definitions" | Only the normalized denominator is hers, and she calls it a *normalized effectiveness measurement*. The focal-method raw denominator is the ISSTA 2026 replication's adaptation. Both now require excluding equivalent mutants, which the source dropped |
| A6 | Gate rules with no report-only mode | Extracted to `add-gate-decision-provenance`; this change now depends on it |
| A17 | No stated ordering against `prove-m8-execution` | Declared as a dependency. Landing first would mint four vacuous M8 cells |

## Findings raised by this change

**R1 — the citation the source used to argue *against* mutation score actually supports it.**
The plan cited the ISSTA 2026 replication as evidence that coverage and mutation are unreliable
proxies. The paper's own abstract says its findings "diverge substantially from prior results": in
regression-style settings over bug-free code under test, inter-model branch coverage correlates with
bug detection at **r = 0.861**, and the proxies fail only when the code under test is already buggy.
Our corpus is bug-free-reference-plus-seeded-mutants, i.e. exactly the regime where the metric
holds. The plan was arguing against its own best evidence; the design now states the regime.

**R2 — "35.9% of Java PRs" is a denominator error worth not repeating.** The figure is 23/64 —
*instrumented code-plus-tests PRs* — from a starting population of 532 Java PRs. Any slide built on
this change should say "of instrumented code-plus-tests PRs" or the claim overstates its scope by
roughly an order of magnitude.

**R3 — `--offline` is not a network kill-switch, and task 2.4 says so.** The source plan's
"confirm zero-network execution" reads as though a flag enforces it. `cli.py` uses `--offline` to
select an in-memory Langfuse client. The zero-external-dependency property comes from the suite's
own lazy imports and absent extras, so the test asserts it directly rather than trusting a flag.

**R4 — MuTAP's 93.57% is a best-of-four configuration on a synthetic-mutant benchmark.** If it is
cited as a reference point for what good looks like, cite it precisely: on the real-bug benchmark
the same tool reports 94.91%, and the four MuTAP configurations range from 89.13% upward. Do not
present one number as the tool's score.

## Deliberately not done

- **No judge.** Every scorer here is decidable by execution, so
  `require_calibration_for_judge_gating` is never engaged and this change does not queue behind
  calibration. That is a scoping decision, not an oversight: `unsupported_assumption` was the one
  judge-backed scorer proposed, and it is deferred for exactly that reason.
- **No coverage delta.** It needs a second instrumented run per item and its own oracle. Deferred
  rather than approximated.
- **No edits to another change's in-flight delta.** The dependency on
  `add-gate-decision-provenance` is declared, not implemented here.

## Open questions for the reviewer

1. Sixty corpus items is a judgement call, not a derived number. The stratification argument
   supports "enough per control-flow category to see a difference"; if the held-out split is to
   support per-stratum claims, it likely needs to be larger. Worth settling before 1.3 freezes.
2. Mutant generation currently has no equivalence detector — items carry equivalence marks from the
   generator. That is sound for synthetic items and will not transfer to any future real corpus.
   Flagged now so it is a known boundary rather than a surprise later.

---

## Implementation record (2026-09-05) — landed as F-065, ADR 0043

### Task 6.4 — the soak's starting distribution

Dry-run over the **held-out split** (11 of 60 items, keyed by `sha256(seed:item_id)`), each
item scored against all four reference suites. Executed against this checkout; the target
ran every suite in a subprocess sandbox against the reference implementation and each
non-equivalent mutant.

| reference suite | `test_executability` | `testgen_mutation_score` (raw) | `testgen_green_on_correct` | `requirement_obligation_recall` |
|---|---|---|---|---|
| `thorough` | 1.00 | 1.00 | 0.00 | 1.00 |
| `weak` | 1.00 | **0.59** | 0.00 | **0.59** |
| `broken` | **0.00** | n/a | n/a | n/a |
| `false_alarm` | 1.00 | 1.00 | **0.35** | 1.00 |

The table's value is what it shows about **independence**, not the absolute numbers:

- `weak` differs from `thorough` on mutation score and recall **and on nothing else** — its
  false-alarm rate stays 0.00.
- `false_alarm` differs from `thorough` on the false-alarm rate **and on nothing else** —
  its mutation score stays 1.00. This is the spec's own scenario ("*a suite that fails on
  correct code is penalised … `testgen_mutation_score` is unchanged by it*"), confirmed
  empirically rather than argued.
- `broken` is non-executable, and the other three report not-applicable rather than zero, so
  an infrastructure failure stays distinguishable from a total agent failure.

The four config bounds (`0.90` / `0.60` / `0.05` / `0.70`) sit inside this range and are
**soak starting points recorded in config**, not spec thresholds. Every rule is advisory.

### Findings from implementation

**F1 — the design predicted no new import edge, and was wrong about one.** `design.md` said
a scorers subpackage "resolves to the existing component and adds no import edge". True of
the package mapping, but the scorers imported the evidence key from `targets/testgen.py`,
which created a real `scorers → targets` edge. The architecture drift guard caught it. The
key moved to `core/types.py` — it is the *contract between* the two, both already depend on
`core`, and the neutral home costs nothing. The design's own instruction ("re-run the drift
guard anyway; the manifest is a protected path precisely so that assumption gets checked
rather than assumed") is what made this a two-minute fix instead of a review finding.

**F2 — obligations had to be redefined before they measured anything.** The first
derivation partitioned the input grid by *output value*, producing a median of 16
obligations per item and a maximum of 43. Those are test cases ("returns 47 for this
input"), not obligations, and a recall denominator built from them would have measured how
exhaustively a suite enumerated the grid. Obligations are now equivalence classes of inputs
under *which mutants detect a difference there* — median 4, max 10 — each with a witness
mutant that provably breaks it. Coverage is then decidable by execution and never inferred
from the suite being scored.

**F3 — three of twelve loop items shipped dead code.** The threshold cycled `0,1,2,3` across
all strata, so `for i in range(0)` made the `loop_branch` predicate unreachable: no mutation
inside it could ever be killed, and the item silently taught nothing about the stratum it
claimed to represent. Thresholds are now per-stratum. Found by *reading a generated item*,
which is the argument for committing the corpus rather than generating it on the fly.

**F4 — the "known-good" suite was enumeration, not coverage.** The first `thorough` suite
asserted all 91 grid points. That is not what a competent engineer writes, and shipping it
as the reference would have made the corpus reward exhaustive enumeration; it also
quadrupled the committed corpus. It is now a greedy minimal covering set — typically two to
four assertions — that still distinguishes every non-equivalent mutant.

**F5 — mutant equivalence is decided, not declared.** A generator that labelled mutations
equivalent *by operator* would put an unchecked claim into the denominator of every mutation
score. Equivalence is determined by evaluating both implementations over the grid, and
`tests/test_testgen_corpus.py` re-derives every mark from the committed sources rather than
trusting the manifest.

**F6 — the 500-line budget fired on the generator**, as it has on every substantial addition
this week. Split into `scripts/_testgen_corpus_lib.py` (pure domain logic: templates,
mutation, obligations, suites) and `scripts/gen_testgen_corpus.py` (assembly, manifest, CLI),
following ADR 0036/0019.

**F7 — M8 would have regressed without a cell.** `prove-m8-execution` had just taken M8 to
39 of 41 components; registering four scorers with no pipeline would have made it 39 of 45
the same day. A `testgen_scorers` M8 pipeline runs the four scorers over the real
suite-execution target, so the artifact reads **43 of 45** — the two uncredited still being
exactly the two waived.

### Verification

- `./scripts/quality-gate.sh all` — PASS (2387 passed / 32 skipped)
- `eval_harness` branch coverage **98.63%** against the 96 floor; scorers 100%,
  `_suite_runner.py` 100%, `targets/testgen.py` 94%
- `scripts` coverage 95.60% against the 85 floor
- `python scripts/validations/F_065.py` — every check established by execution, including a
  negative control that a suite red on correct code kills nothing
- `python scripts/gen_testgen_corpus.py --check` — the committed corpus regenerates
  byte-identically
- `drift_check.py` — no undocumented dependencies after F1

### Still owed before archive

The `spec-guardian` conformance pass and the `peer-reviewer` adversarial pass (task 6.6).
Both are `claude-foundation/` fleet roles staged in-tree rather than installed (ADR 0028),
and need a session started with `claude --plugin-dir claude-foundation`. Not run here; the
findings above are the implementer's own record, which is not a substitute for either.

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

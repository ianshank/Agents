# The two-pass review protocol

The single-pass "critique against the quality standards" review catches style and
structure defects but reliably misses the two failure modes that actually ship:
**claims that were never true** (the plan cites a file, a behaviour, a CI guarantee that
the tree does not contain) and **designs that collide with an invariant nobody named**
(a CI gate, a type contract, a protected path). The two passes below target exactly
those, in that order, before the standards critique runs.

## Pass 1 — mechanical fact-check

*Goal: no claim survives on the authority of the document that made it.*

1. **Pin the tree.** Record the commit SHA the review re-derives against, in the findings
   header. A review against "the repo" is unreproducible; a review against `4ceed30` can
   be re-run.
2. **Enumerate falsifiable claims.** Every file path, line reference, count, behaviour
   ("X fails when Y"), CI claim ("gated by Z"), and absence claim ("no test covers W") in
   the package is a claim to check. Absence claims need positive evidence (`grep`/`git log`
   output), not absence of retrieval — *absence of retrieval is not evidence of absence*.
3. **Re-derive, don't re-read.** Run the command, execute the config, read the file at the
   cited line. A claim about a gate is checked by running the gate.
4. **Verdict per claim**, with the evidence inline:
   - **CONFIRMED** — re-derivation matched the claim.
   - **CORRECTED** (or PARTIALLY TRUE) — the direction was right, the specifics were not;
     record both the claim and the measured reality.
   - **REFUTED** — the tree contradicts the claim; record the disproof.

## Pass 2 — adversarial design review

*Goal: the design is attacked by a reviewer trying to make it fail, not confirmed by one
hoping it works.*

1. **Attack surfaces to probe:** CI-enforced invariants the package never names
   (protected paths, coverage floors, schema gates, drift guards); type/contract
   mismatches against the actual code; silent-drift paths (a hand-maintained list, an
   unguarded generated artifact, a check that compares text instead of evaluating
   policy); vacuous verification (a test that passes against the mutation it exists to
   catch); ordering/lifecycle problems (self-referencing SHAs, same-PR archival).
2. **Verify each attack before keeping it.** An attack is itself a claim — re-derive it.
   Mutation-prove where possible: gut the behaviour and show the check stays green.
3. **Refuted attacks are recorded, never deleted.** A risk that was raised, checked, and
   dismissed with evidence is exactly what the next reviewer would otherwise re-raise.
   Keep a "attacks that died under verification" section.

## Findings order (the output contract)

1. **Confirmed premises** — what pass 1 verified the package got right.
2. **Defects found in the tree during review** — real, pre-existing defects the review
   surfaced (these become fix obligations of the change, or recorded follow-ons).
3. **Corrections that reshaped the design** — where pass 1/2 changed the plan, with the
   before/after and the evidence that forced it.
4. **Attacks that died under verification** — pass 2's refuted attacks, kept per above.

Then, and only then, the rewritten package.

## Worked examples (this repository)

- **`openspec/changes/archive/add-eval-matrix-completeness/review.md`** — the review that shaped
  the F-053 matrix-completeness change. Pass 1 pinned `4ceed30` and, among other things,
  *executed* the shipped `config/trajectory_eval.yaml` and found it failing its own gate
  (pass_rate 0.0 vs min 0.9) behind a covering test that asserted only non-emptiness, and
  proved `--cov=F_052` dead via the coverage warning. Pass 2 killed the original derived-M7
  direction (aliases are not in `Registry.names()`), the `"type"`-literal M8 extraction
  (`braintrust`/`langfuse` exist in two registries), and the original sink floor (it
  contradicted its own fill list) — each correction recorded with the disproof. Three
  attacks died under verification and are kept in the file.
- **`docs/plans/agent-eval-coverage/REVIEW.md`** — the house precedent: two externally
  produced documents re-checked claim-by-claim against `b52c696`. Roughly a third of one
  document's coverage matrix failed pass 1 (it graded capabilities "Not Covered" on
  failed retrieval), and pass 2 showed three of the other's five proposed changes would
  have failed CI on first push against invariants it never named. The corrected plan and
  change packages superseded both documents.

A second application of the same protocol *after* implementation (the F-053 hardening
pass, recorded in `CHANGELOG.md` and `NEXT_STEPS.md`) caught the feature shipping its own
defect class — assertion-free floor cells, a false "transitively verified" validator
claim, and an entire skipped-in-CI cell class the artifact certified as covered. Running
the two passes once at proposal time and once at pre-merge time is the recommended cadence
for changes that themselves make coverage claims.

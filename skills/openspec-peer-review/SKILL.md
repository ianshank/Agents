---
name: openspec-peer-review
version: 1.1.0
description: Emits an objective Peer Review Findings section and rewrites an OpenSpec package to satisfy quality standards. Use this whenever the user asks to review, critique, or polish an existing plan, or as the final step in generating an OpenSpec package.
---

# openspec-peer-review — E2E Action Skill

Perform **OpenSpec peer review** end to end: take an existing OpenSpec package, emit objective review findings, and rewrite the package to meet quality standards.

## 1. Preconditions (input contract)

- The user has provided an existing OpenSpec package or plan.
- You have reviewed the composition contract and examples in `references/research-application.md`.

## 2. Procedure (the E2E steps)

Execute the following review protocol (long form + worked examples in
`references/two-pass-protocol.md`):

1. **Pass 1 — mechanical fact-check.** Pin the tree under review (record the commit SHA).
   Re-derive every falsifiable claim in the package against that tree — run the command,
   read the file:line, execute the config — and record a per-claim verdict:
   **CONFIRMED / CORRECTED / REFUTED**, each with evidence. No claim is accepted on the
   strength of the source document alone.
2. **Pass 2 — adversarial design review.** Attack the design: failure modes, CI-invariant
   collisions, contract mismatches, silent-drift paths. Verify each attack before keeping
   it; an attack that dies under verification is **recorded as refuted, never deleted** —
   a reviewed-and-rejected risk is information the next reviewer needs.
3. **Critique**: Analyze the input package against the quality standards defined by `openspec-quality-plan` (mandatory "Code Hygiene & Quality Gates", phase-level hygiene gates, backwards compatibility, zero hard-coded configuration).
4. **Emit Findings**: Output a "Peer Review Findings" section explicitly listing the shortcomings and necessary improvements, ordered **confirmed premises → defects found in the tree → corrections that reshaped the design → refuted attacks**. **This section must appear before any rewritten files.**
5. **Rewrite**: Rewrite the entire OpenSpec package incorporating the improvements, ensuring it fully meets every quality standard.

## 3. Output contract (postconditions — what "done" means)

- A "Peer Review Findings" section appears *first*, in the pass-derived order above, with
  the reviewed tree's SHA and a verdict + evidence per falsifiable claim.
- A rewritten OpenSpec package follows the findings.
- The rewritten package strictly satisfies the `openspec-quality-plan` standards.
- Refuted attacks from pass 2 remain in the findings (marked refuted), not silently dropped.

## 4. Failure handling

- If the input is not a recognizable plan, ask for a valid OpenSpec package.

## 5. Validation gate (before declaring success)

**Subjective skill validation:**
There is no honest scripted gate for the quality of a peer review.
- Run **structural only** (`python scripts/validate_skill.py --skill . --tier structural`) to keep the metadata/triggering honest.
- Self-check against explicit, concrete criteria:
  1. **Findings Ordered First**: The "Peer Review Findings" section is the first element of the output.
  2. **Standards Met**: The rewritten package includes the "Code Hygiene & Quality Gates" and phase-level hygiene gates.
  3. **Claims Pinned**: Pass 1 names the tree SHA it re-derived against, and every falsifiable claim carries a CONFIRMED / CORRECTED / REFUTED verdict with evidence.
  4. **Refuted Attacks Kept**: Pass 2's rejected attacks appear in the findings, marked refuted.

## 6. Examples

See `references/research-application.md` for concrete examples, and
`references/two-pass-protocol.md` for two full worked reviews from this repository.

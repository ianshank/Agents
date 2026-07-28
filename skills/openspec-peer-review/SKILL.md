---
name: openspec-peer-review
version: 1.0.0
description: Emits an objective Peer Review Findings section and rewrites an OpenSpec package to satisfy quality standards. Use this whenever the user asks to review, critique, or polish an existing plan, or as the final step in generating an OpenSpec package.
---

# openspec-peer-review — E2E Action Skill

Perform **OpenSpec peer review** end to end: take an existing OpenSpec package, emit objective review findings, and rewrite the package to meet quality standards.

## 1. Preconditions (input contract)

- The user has provided an existing OpenSpec package or plan.
- You have reviewed the composition contract and examples in `references/research-application.md`.

## 2. Procedure (the E2E steps)

Execute the following review protocol:

1. **Critique**: Analyze the input package against the quality standards defined by `openspec-quality-plan` (mandatory "Code Hygiene & Quality Gates", phase-level hygiene gates, backwards compatibility, zero hard-coded configuration).
2. **Emit Findings**: Output a "Peer Review Findings" section explicitly listing the shortcomings and necessary improvements. **This section must appear before any rewritten files.**
3. **Rewrite**: Rewrite the entire OpenSpec package incorporating the improvements, ensuring it fully meets every quality standard.

## 3. Output contract (postconditions — what "done" means)

- A "Peer Review Findings" section appears *first*.
- A rewritten OpenSpec package follows the findings.
- The rewritten package strictly satisfies the `openspec-quality-plan` standards.

## 4. Failure handling

- If the input is not a recognizable plan, ask for a valid OpenSpec package.

## 5. Validation gate (before declaring success)

**Subjective skill validation:**
There is no honest scripted gate for the quality of a peer review.
- Run **structural only** (`python scripts/validate_skill.py --skill . --tier structural`) to keep the metadata/triggering honest.
- Self-check against explicit, concrete criteria:
  1. **Findings Ordered First**: The "Peer Review Findings" section is the first element of the output.
  2. **Standards Met**: The rewritten package includes the "Code Hygiene & Quality Gates" and phase-level hygiene gates.

## 6. Examples

See `references/research-application.md` for concrete examples.

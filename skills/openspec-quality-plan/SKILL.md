---
name: openspec-quality-plan
version: 1.0.0
description: Generates a complete OpenSpec change package containing proposal, design, and task specs. Use this whenever the user asks to create an implementation plan, an OpenSpec package, or convert a research leaf node into a concrete project plan.
---

# openspec-quality-plan — E2E Action Skill

Perform **OpenSpec package generation** end to end: take a feature request or research leaf node, produce a complete OpenSpec package (`proposal.md`, `design.md`, `tasks.md`, and behavioural delta specs), and prove it worked before reporting success.

## 1. Preconditions (input contract)

- The user has provided a feature request or a surviving leaf node from a brainstorming session.
- You have reviewed the composition contract and examples in `references/research-application.md`.

## 2. Procedure (the E2E steps)

Execute the following generation protocol:

1. **Proposal**: Write `proposal.md` with the background, goals, and non-goals.
2. **Design**: Write `design.md`. You **must** include a "Code Hygiene & Quality Gates" section that explicitly lists:
   - Required tooling (e.g., `ruff`, `mypy`).
   - Test coverage targets (determine dynamically based on criticality, strictly enforced).
   - Configuration strategy (zero hard-coded values).
   - Backwards-compatibility approach.
3. **Tasks**: Write `tasks.md`. You **must** end every implementation phase with a concrete hygiene/test gate (e.g., "Run quality-gate.sh all and fix issues").
4. **Behavioural Deltas**: Include pure behavioural delta specs if applicable.

## 3. Output contract (postconditions — what "done" means)

- A complete OpenSpec package is produced.
- `design.md` explicitly lists tooling, coverage, configuration, and compatibility under a "Code Hygiene & Quality Gates" section.
- `tasks.md` ends every phase with a hygiene/test gate.

## 4. Failure handling

- On failure to meet the constraints, explain what was missing and regenerate the output.

## 5. Validation gate (before declaring success)

**Subjective skill validation:**
There is no honest scripted gate for the quality of an OpenSpec package.
- Run **structural only** (`python scripts/validate_skill.py --skill . --tier structural`) to keep the metadata/triggering honest.
- Self-check against explicit, concrete criteria:
  1. **Mandatory Sections Present**: The "Code Hygiene & Quality Gates" section is present in `design.md`.
  2. **Phase Gates Present**: Every phase in `tasks.md` ends with a hygiene/test gate.

## 6. Examples

See `references/research-application.md` for concrete examples.

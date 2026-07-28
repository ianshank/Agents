---
name: hierarchical-recursive-brainstorm
version: 1.0.0
description: Decomposes a topic into a controlled hierarchy, recursively expands leaves, prunes the bottom quartile, and synthesizes upward into a self-explanatory Markdown tree. Use this whenever the user asks to research a complex topic, brainstorm agent evaluation patterns, or requires a rigorous structural breakdown of ideas.
---

# hierarchical-recursive-brainstorm — E2E Action Skill

Perform **controlled hierarchical research** end to end: take a broad research question, produce a pruned and synthesized Markdown tree of findings, and prove it worked before reporting success.

## 1. Preconditions (input contract)

- The user has provided a clear research topic or question.
- You have reviewed the composition contract and examples in `references/research-application.md`.

## 2. Procedure (the E2E steps)

Execute the following hierarchical research protocol:

1. **Decompose**: Break the initial topic into 2-5 distinct sub-topics (branches).
2. **Expand**: Recursively explore each branch. Stop expanding when you reach the configured `max_depth` (default: 3) or when a branch is sufficiently detailed.
3. **Prune**: Evaluate the leaves of the tree and prune the bottom quartile (the least relevant, least feasible, or weakest ideas).
4. **Synthesize**: Moving from the leaves up to the root, write a brief synthesis paragraph for every surviving parent node that summarizes its children.
5. **Output**: Generate the final output as a self-explanatory Markdown tree. 
6. **Action**: Conclude the output with a "Next Actions" paragraph detailing the most promising paths forward.

### Tunable Parameters (Agent Overrides)
These limits apply unless you explicitly decide to override them based on the task:
- `max_depth`: (configurable, determine dynamically based on topic breadth)
- `max_children`: (configurable, determine dynamically based on topic breadth)
- `prune_quartile`: (configurable, determine dynamically based on leaf density)

**CRITICAL RULE**: Do not invent or hallucinate external knowledge. Rely on your existing knowledge and any provided context or searches.

## 3. Output contract (postconditions — what "done" means)

- A final Markdown tree is produced containing the surviving ideas.
- Synthesis is present for every surviving parent node.
- A "Next Actions" paragraph exists at the end.
- The bottom quartile of ideas has been demonstrably pruned.
- The depth and branch limits were respected.

## 4. Failure handling

- On failure (e.g., if the topic is too broad to decompose meaningfully), report the specific issue and ask the user to refine the scope.
- Do not produce a partial or hallucinated tree.

## 5. Validation gate (before declaring success)

**Subjective skill validation:**
There is no honest scripted gate for the quality of research.
- Run **structural only** (`python scripts/validate_skill.py --skill . --tier structural`) to keep the metadata/triggering honest.
- Self-check against explicit, concrete criteria:
  1. **Limits Respected**: Max depth and branch limits were not exceeded.
  2. **Pruning Applied**: The bottom quartile of leaves was absent from the final output.
  3. **Synthesis Present**: Every parent node has a synthesis of its children.
  4. **Next Actions Present**: The output concludes with a "Next Actions" paragraph.
  5. **No Hallucinations**: No external knowledge was invented.

## 6. Examples

See `references/research-application.md` for concrete examples of applying this skill to agent-evaluation research.

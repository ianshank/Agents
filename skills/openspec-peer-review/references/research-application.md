# Research Application Patterns

## Composition Contract
This skill is Step 3 in the end-to-end research pipeline. 
1. **hierarchical-recursive-brainstorm** expands a research question into a pruned tree.
2. **openspec-quality-plan** turns the strongest leaves into a full OpenSpec package.
3. **openspec-peer-review** critiques and rewrites that package to the quality standards.

## Concrete Review Examples

The following are examples of how OpenSpec plans are critiqued and rewritten.

### Example 1: Trace Reconstruction (Snorkel)
- **Input Plan**: An OpenSpec package lacking phase-level hygiene gates in `tasks.md`.
- **Peer Review Findings**: 
  - "The `tasks.md` file fails to include a test gate after the simulation generation module."
  - "The `design.md` file fails to explicitly declare a backwards compatibility strategy."
- **Rewritten Package**: The package is fully regenerated, ensuring the missing gates and strategy are documented.

### Example 2: Closed-Loop Evals & Reward Hacking (Uber)
- **Input Plan**: A plan hard-coding the reward-hacker adversarial configurations.
- **Peer Review Findings**:
  - "The `design.md` file incorrectly hard-codes the adversarial prompt limits instead of using an injectable configuration strategy."
- **Rewritten Package**: The package is rewritten, adding a configuration block that delegates parameters to the invoking agent.

# Research Application Patterns

## Composition Contract
This skill is Step 2 in the end-to-end research pipeline. 
1. **hierarchical-recursive-brainstorm** expands a research question into a pruned tree.
2. **openspec-quality-plan** turns the strongest leaves into a full OpenSpec package.
3. **openspec-peer-review** critiques and rewrites that package to the quality standards.

## Concrete Plan Examples

The following are examples of how leaf nodes from agent-evaluation research convert into OpenSpec plans.

### Example 1: Trace Reconstruction (Snorkel)
- **Input Leaf**: "Implement a Trace-to-Simulation pipeline..."
- **Plan Elements**: 
  - `design.md` specifies strict typing (`mypy --strict`) and 95% coverage for the pipeline components. It outlines the schema for parameterized mock environments.
  - `tasks.md` includes a hygiene gate after the extraction module and after the simulation generation module.

### Example 2: Closed-Loop Evals & Reward Hacking (Uber)
- **Input Leaf**: "Deploy an adversarial 'reward-hacker' diagnoser agent..."
- **Plan Elements**:
  - `design.md` specifies the configuration strategy for the adversarial agent, ensuring tunable reward-seeking behavior without hard-coded limits.
  - `tasks.md` places a test gate after the adversarial prompt generation phase, asserting that it complies with safety constraints.

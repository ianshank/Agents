# Research Application Patterns

## Composition Contract
This skill is Step 1 in the end-to-end research pipeline. 
1. **hierarchical-recursive-brainstorm** expands a research question into a pruned tree.
2. **openspec-quality-plan** turns the strongest leaves into a full OpenSpec package.
3. **openspec-peer-review** critiques and rewrites that package to the quality standards.

## Concrete Leaf Examples

The following are examples of how broad agent-evaluation research topics decompose into concrete, actionable leaf nodes during the brainstorm process.

### Example 1: Trace Reconstruction (Snorkel)
- **Root**: "How do we create private benchmarks from production traces?"
- **Surviving Leaf Node**: "Implement a Trace-to-Simulation pipeline that extracts production Langfuse traces, strips PII, and generates a parameterized mock environment where a diagnoser agent can attempt to recreate the trace's failure modes against an oracle verifier."

### Example 2: Closed-Loop Evals & Reward Hacking (Uber)
- **Root**: "How do we guard against reward hacking in closed-loop evaluations?"
- **Surviving Leaf Node**: "Deploy an adversarial 'reward-hacker' diagnoser agent during the offline evaluation phase that specifically tries to maximize the reward function via degenerate behavior. If the adversarial agent succeeds, the evaluation environment's guardrails must be tightened before online deployment."

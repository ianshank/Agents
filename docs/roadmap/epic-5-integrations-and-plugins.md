# Epic 5: Integrations & Plugin Ecosystem

## Focus Area
LLM observability sinks, evaluation client bridges, third-party backend validation, and Claude Code plugin hosting.

## Landed Features & Milestones
- **[x] First-Class Langfuse Integration**: Dataset fetching, experiment logging, score submission, prompt management (`PromptSourceConfig`), and comparison exports.
- **[x] BrainTrust Integration (F-038)**: Result sink, dataset source, autoevals scoring bridge, and client injection seam (`braintrust_client`).
- **[x] Phoenix Integration Spike & Live CI**: OTLP tracing, eval judge integration, and opt-in `.github/workflows/phoenix-live.yml`.
- **[x] Claude Foundation Plugin Staging (ADR 0017, ADR 0028)**: Full staging directory under `claude-foundation/` with manifests, skills, subagents, and hooks.
- **[x] Backend Validation Framework (`experiments/backend-validation/`)**: Isolated 6-phase capability validation for evaluation backend displacement decisions.

## In Progress & Planned
1. **Extract `claude-foundation` to Dedicated Repository**:
   - Move `claude-foundation/` to `ianshank/claude-foundation`.
   - Setup standalone CI and release v1.0.0.
   - Install as pinned external plugin per ADR 0017.
2. **Execute Live Backend Validation**:
   - Human TCB sign-off and live container stack testing for Langfuse vs Opik benchmarks.
3. **Live BrainTrust CI Workflow**:
   - Add `.github/workflows/braintrust-live.yml` (mirroring `phoenix-live.yml`).

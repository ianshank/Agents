# ADR-0001 — Use OpenAI-compatible API for LLM judge integration
**Status:** accepted
**Context:** The eval harness needed LLM-as-judge support beyond the existing BedrockJudge. NVIDIA Nemotron and local LM Studio both expose OpenAI-compatible APIs. Building a generic OpenAI judge covers both and any future OpenAI-compatible provider.
**Decision:** Implement OpenAIJudge using the openai Python SDK with configurable base_url, model, and optional extra_body. Use streaming internally to capture reasoning_content. Add robust JSON extraction (regex) and exponential backoff retry (tenacity) for rate limits.
**Consequences:** Depends on openai SDK (optional dep). extra_body is provider-specific and may need documentation per provider. Streaming adds minor complexity but ensures reasoning trace capture.
**Related features:** F-002

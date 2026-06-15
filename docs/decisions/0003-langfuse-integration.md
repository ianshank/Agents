# ADR-0003 — Langfuse Tracing and Hosted Evaluation Integration

**Status:** accepted

**Context:**
We need to support first-class tracing and dataset-hosting integrations with Langfuse, utilizing the user's specific credentials while maintaining backwards compatibility and offline support. Specifically:
- Secret key: `sk-lf-e220d788-d2e0-4e82-bbde-6d1a57ba149f`
- Public key: `pk-lf-ad617cfc-ce1b-4c23-8c76-7868605ee6f1`
- Base URL: `https://us.cloud.langfuse.com`

**Decision:**
1. **Default Fallback Credentials:** Configure `SDKLangfuseClient` constructor to fall back to the provided keys if not found in environment variables.
2. **Auto-Observability Tracing:** Decorate `EvalEngine.run` and `EvalEngine._run_one` with a custom `@observe()` wrapper. The wrapper imports `langfuse.decorators.observe` if the library is present, otherwise defaulting to a transparent no-op decorator.
3. **Trace-to-Item Linking:** Retrieve the active trace ID inside `_run_one` using `langfuse_context.get_current_trace_id()`. If a real `SDKLangfuseClient` is attached, call the REST API client `self._lf.api.dataset_run_items.create` to explicitly link evaluations to dataset runs in Langfuse.
4. **OpenAI Judge Observability:** Swap `OpenAIJudge` client to use `from langfuse.openai import OpenAI` when real Langfuse client is attached, capturing token counts, cost, and streaming reasoning/thinking traces (`reasoning_content`) automatically.

**Consequences:**
- Evaluation runs are traced in real-time on Langfuse with zero-config default settings.
- Fully backwards-compatible; runs in offline mode without throwing import errors when `langfuse` package is absent.
- Links trace runs to datasets, forming a cohesive experiment hub.

**Related features:**
- F-005

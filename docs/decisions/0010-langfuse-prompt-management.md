# 0010 — Langfuse judge-prompt management (opt-in, YAML-fallback)

- Status: **Accepted.** Additive, default-off; the offline/YAML path is unchanged.
- Date: 2026-06-30
- Related: ADR 0003 (Langfuse integration), F-002 (OpenAI judge), F-005 (tracing),
  `src/eval_harness/prompts.py`, `src/eval_harness/langfuse_client/__init__.py`.

## Context

Judge system prompts are currently inline strings in the eval config YAML (e.g. an
`openai`/`bedrock`/`anthropic` judge's `system` param). Teams that manage prompts centrally
want to pull the judge rubric from the **Langfuse prompt registry** (versioned, label-routed
— e.g. `production`) instead of duplicating it in every config. This must not add a hard
dependency, must not break offline runs, and must keep every existing config working
untouched.

## Decision

Add a small **prompt-source seam** resolved at engine-construction time.

1. **`PromptSourceConfig`** (`config/models.py`): `source` is `yaml` (default) or `langfuse`;
   `text` is the inline/fallback prompt; `name`/`version`/`label` address a Langfuse prompt.
   Validation: `langfuse` requires `name`; `yaml` requires `text`. No literal lives in code.
2. **`EvalConfig.judge_prompt`** is an optional `PromptSourceConfig` (absent by default).
   `SCHEMA_VERSION` is unchanged — it is an additive optional field, so old configs parse and
   migrate untouched.
3. **`LangfuseClient.get_prompt`** is a **non-abstract** method defaulting to `None`, so
   existing third-party subclasses keep working and the offline `NullLangfuseClient` needs no
   change. `SDKLangfuseClient.get_prompt` calls the real SDK and **fails safe** (any
   SDK/network error → `None`), mirroring the no-op tracing fallback in F-005.
4. **`resolve_prompt`** (`prompts.py`): `yaml` → inline `text`; `langfuse` →
   `client.get_prompt(...)` when a client is wired and returns text, else the inline `text`
   fallback. Returns `None` only when a Langfuse prompt is missing *and* no fallback text was
   given.
5. **Wiring** (`engine.from_config`): when `judge_prompt` is set, the resolved prompt is
   injected as the judge's `system` param *before* the judge is constructed, so judge classes
   are untouched. Absent `judge_prompt`, the judge params are byte-identical to before.

## Consequences

- **Backwards compatible.** No schema bump, no judge-class change, offline path unchanged;
  `judge_prompt` applies to judges that accept a `system` param (openai/bedrock/anthropic).
- **Fail-safe.** A missing `langfuse` install, missing client, or missing/renamed prompt
  degrades to the inline `text` (or leaves the judge's own `system` when no fallback) rather
  than breaking the run.
- **Tested offline.** `tests/test_langfuse_prompts.py` covers validation, resolution (yaml /
  langfuse-available / langfuse-fallback / none), the mocked SDK `get_prompt` (success /
  network-failure / non-string), and the `from_config` injection; `scripts/validations/F_026.py`
  is offline and needs no Langfuse install. ≥96% branch coverage; ruff + strict mypy clean.

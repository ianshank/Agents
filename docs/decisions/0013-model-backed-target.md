# 0013 — Real model-backed target (additive, opt-in)

- Status: **Accepted.** Additive, opt-in; the existing target types are untouched.
- Date: 2026-06-30
- Related: F-024 (multi-model comparison), F-025 (A/B campaigns), F-002 (OpenAI judge),
  `src/eval_harness/targets/model.py`, `src/eval_harness/judges/__init__.py`.

## Context

`targets/` shipped only `EchoTarget` and `CallableTarget` — there was no LLM-backed
target. ADR 0011 and F-024/F-025 both flagged this explicitly: multi-model comparison and
A/B campaigns were built as orchestration over the target abstraction, but could only be
exercised against `echo`/`callable`. To compare or A/B-test *real* models, the harness
needs a target that calls a live model and returns its completion to be scored.

The provider mechanics already exist in the judges (`OpenAIJudge`, `BedrockJudge`,
`AnthropicJudge`): client construction, env-sourced credentials, tenacity rate-limit
backoff, streamed-delta accumulation. The question was how to reuse them without (a)
importing `judges` from `targets` — the architecture manifest declares `targets: [core,
plugins]`, so that edge would trip the F-009 drift gate — or (b) editing `judges`, a
protected eval-defining path.

## Decision

1. **New `ModelTarget`** (`src/eval_harness/targets/model.py`), registered as
   `@TARGETS.register("model", aliases=("llm",))`. It supports three providers
   (`openai` | `bedrock` | `anthropic`) selected by a config discriminator, builds the
   **same** provider clients the judges build, and returns the raw completion text as
   `TargetOutput.output` (a target is scored; it does not parse a JSON verdict).
2. **Reuse the pattern, not the classes.** The ~handful of client-construction lines and
   the openai streaming/retry block are deliberately duplicated from the judges so
   `targets` stays dependent on `core`/`plugins` only and the protected `judges` file is
   untouched. This mirrors the repo's existing intentional duplication (the vendored
   skill `validate_skill.py` copies behind the drift guard, ADR 0009).
3. **No engine or config-schema change.** `target: ComponentSpec` already carries arbitrary
   `params`, so `SCHEMA_VERSION` stays `1.0` and `EvalEngine.from_config` wires the new
   target automatically (precedent: F-022 `judge_budget`, F-024 `comparison`). It drops
   straight into F-024 `ModelSpec.target` and F-025 arms with zero changes there.
4. **No hard-coded values.** `provider`, `model`, `base_url`, `region`, `prompt_template`,
   sampling params and `extra_body` all come from `params`; credentials are env-only
   (openai key via the SDK's env fallback, bedrock via boto3's chain, anthropic via
   `ANTHROPIC_API_KEY`). The shipped `examples/model_target.yaml` uses `${VAR:-default}`
   interpolation and contains no secrets. `temperature` is omitted for Bedrock/Anthropic
   when `None`, honouring the Opus-4.x "no sampling params" contract (as `AnthropicJudge`).
5. **Dependency-injection seam.** `ModelTarget(client=...)` accepts a pre-built client so
   the whole completion/latency/error/prompt path is unit-tested with stubs — no network,
   no real SDK client. Only the bare `_build_*` SDK-construction lines carry
   `# pragma: no cover` (as `BedrockJudge` does).

## Consequences

- **Backwards compatible.** No schema bump, no change to `echo`/`callable`, no engine edit,
  no new dependency (the `openai`/`bedrock`/`anthropic` extras already exist for the judges).
- **Airgap preserved.** No new component edge — `drift_check.py` still matches the manifest.
- **Tested offline.** `tests/test_model_target.py` covers all three providers, the
  streaming/no-choices/retry branches, latency/metadata, the error and prompt-template
  paths; `scripts/validations/F_027.py` runs with a stub client. ≥96% branch coverage held;
  ruff + mypy clean.
- **Follow-up.** A live smoke test (`eval-harness run --config examples/model_target.yaml`)
  needs real credentials and is out of the offline gate by design.

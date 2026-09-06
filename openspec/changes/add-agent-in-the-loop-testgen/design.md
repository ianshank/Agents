## Owner defaults (recorded)

Locked 2026-09-06 in [`OWNER_DEFAULTS.md`](./OWNER_DEFAULTS.md) (board proceed): option **(a)**, prompt held constant, `repetitions: 5`, held-out via manifest/config allowlist + CI test, offline-only CI with credential-gated live model, weak corpus + empty/null baseline, Deck B CI advisory `report_only`, testgen-only outer allowlisted runner.

# Design: add-agent-in-the-loop-testgen

## Recommended composition (option a)

```
focal method + obligations  →  GeneratorTarget (model|callable, DI client)
                            →  suite artifact (same shape as corpora/testgen inputs.suite)
                            →  eval_harness.targets.testgen:run_generated_suite
                            →  existing F-065 scorers
```

The outer runner is itself a `TargetRunner` registered under an explicit allowlist entry (ADR 0039). Tests inject a fake generator that returns fixtures; CI offline jobs never open sockets.

## Artifact contract

Reuse the F-065 suite evidence already consumed by `test_executability`, `testgen_mutation_score`, `testgen_green_on_correct`, and `requirement_obligation_recall`.

Do not invent parallel metadata keys. If the generator cannot produce a suite, fail closed with structured evidence the scorers already treat as not applicable / failure.

## Held-out protocol

- Generator development uses only non-held-out corpus items.
- Deck B figures quote the sequestered split only.
- Config or manifest key enforces the split; a test asserts the offline job cannot point at training items by accident.

## Gates

Day-one rules are `report_only` / advisory, matching F-065. No blocking threshold until soak distributions exist and an owner sets bounds deliberately.

## Backwards compatibility

- Existing `config/testgen_eval.yaml` (corpus-supplied suite → callable) remains valid and is the Deck A+ calibration path.
- New config profile (e.g. `config/testgen_agent_eval.yaml`) opts into the pipeline target.
- Prefer additive config fields over a `SCHEMA_VERSION` bump.

## Logging / DI

- Injected clock, client, and allowlist resolution.
- Structured logs for generator attempt id, prompt hash (not raw secrets), suite hash, execution evidence pointers.
- No WAN imports in the offline path.

## Alternatives rejected for v1

- Engine-level multi-target graphs (option b) — defer until a second scenario needs them.
- External shell orchestration (option c) — splits provenance out of `RunResult`.

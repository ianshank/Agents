# 0048 — Agent-in-the-loop test generation: sequential pipeline, suite stripping, holdout allowlist

- Status: **Accepted.**
- Date: 2026-09-08
- Related: `openspec/changes/archive/add-agent-in-the-loop-testgen/` (design, tasks, owner defaults),
  ADR 0043 (the target executes, the scorers read), ADR 0038 (item error policy),
  ADR 0039 (callable allowlist, only for optional `generator_path`), F-065, F-069.

## Context

Deck A+ can present the measurement system: F-065 scorers, a sandboxed executor, and a
frozen corpus that supplies `inputs.suite`. Deck B ("first agent results") cannot, because
nothing in the harness makes an agent write a suite, and a run carries exactly one
`target`. Scoring the corpus's own reference suite as if an agent produced it is the
homework attack.

Owner defaults (2026-09-06) locked option (a): a sequential pipeline `TargetRunner`, prompt
held constant, `repetitions: 5`, holdout via config allowlist, offline-only CI, weak slice
plus empty/null baseline beside the agent, advisory gates until soak.

`targets/testgen.py` is 459/500 lines, so the pipeline cannot live there.

## Decision

1. **One registered pipeline target.** `testgen_agent` generates a suite from focal method
   + obligations, then calls `run_generated_suite` in-process. The F-065 scorers are
   unchanged. No engine-level multi-target graph (option b) until a second scenario needs
   it.
2. **Strip `inputs.suite` before generate.** The generator sees a copy of the item with
   that key removed. A generator whose only trick is `item.inputs["suite"]` cannot see
   it. The original item is not mutated; execution overwrites `suite` on a payload dict
   passed to `run_generated_suite`.
3. **Registered name, not an allowlist entry.** Selecting `type: testgen_agent` is a
   registry lookup. ADR 0039 applies only if `generator_path` names `module:attr`. Never
   allowlist `eval_harness`. YAML cannot inject a Python callable; tests inject `generate=`.
   A missing generator fail-closes with structured empty evidence (ADR 0038).
4. **Holdout via `allowed_splits`.** The Deck B profile sets `[holdout]`. Train items fail
   closed. Quote **thorough holdout, n=11 unique**. Do not quote `pass^k` from a
   deterministic fake — `is_deterministic` is True for the injected-fake path, so
   `deterministic_sampling` fires honestly.
5. **Every gate rule is advisory** (`report_only`, F-062), matching F-065.

## Consequences

- New file `src/eval_harness/targets/testgen_agent.py`; side-import in
  `targets/__init__.py`. `config/testgen_eval.yaml` stays the Deck A+ path.
- Target-kind matrix row M1/M2/M3/M6 plus an M8 pipeline.
- Live `model` generation belongs in a credential-gated workflow, never the default
  offline job.

## Alternatives considered

- **Engine-level multi-step chaining (option b):** deferred until a second scenario
  proves the pattern.
- **External shell orchestration (option c):** rejected — splits provenance out of
  `RunResult`.
- **Allowlisting the outer runner as a callable path:** confused with ADR 0039; a
  registered target is not a config-named import.

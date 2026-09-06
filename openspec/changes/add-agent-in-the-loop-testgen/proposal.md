# Change: add-agent-in-the-loop-testgen

**Status:** proposed · **Date:** 2026-09-06 · **Author track:** Cody / docs lane
**Motivated by:** `docs/plans/scenario-eval-matrices/DELIVERY.md` revision 2 §4-§7 (Deck B blocked on subject, not scorers) and `DECK_A_PLUS.md`.
**Depends on:** `add-testgen-eval-matrix` (implemented — F-065 scorers, corpus, allowlisted callable target).
**Compiles down to:** a design ADR claimed at land + F-ID claimed at land (never reserved here).

## Why

Deck A can present the measurement system today. Deck B ("first agent results") cannot, even though the test-generation **scorers, synthetic corpus, and sandboxed suite executor are already shipped**.

The missing piece is the **subject**: nothing in the harness makes an agent write a test suite, and nothing chains two targets. A run carries exactly one `target: ComponentSpec`. `CompareSpec` (F-024) evaluates several targets **side by side on the same dataset**, not in sequence. The testgen corpus supplies `inputs.suite` ready-made; the registered targets are `echo`, `callable`, and `model`.

Without a generation step upstream of `eval_harness.targets.testgen:run_generated_suite`, every perfect score on the shipped config is the corpus grading its own homework.

## What changes (proposed)

1. A **composition** that turns focal method + gold obligations into an agent-authored suite, then feeds that suite into the existing allowlisted execution target.
2. Config/schema support for that composition (see options below) without weakening ADR 0039 deny-by-default allowlisting.
3. Held-out protocol: agent-generated suites scored only on sequestered items; no iteration on the held-out split.
4. Advisory (`report_only`) gate rules only on day one — same posture as F-065.
5. Docs: Deck B estimate becomes dated only after this design is decided.

## Options (recommendation marked)

| Option | Shape | Upside | Downside |
|---|---|---|---|
| **(a) Sequential pipeline target (recommended default)** | One outer `TargetRunner` that calls a generator (model/callable) then the existing `run_generated_suite` | Keeps single-`target` run shape; reuses F-065 evidence contract; smallest blast radius | Outer target becomes privileged; must stay allowlisted and offline-testable via DI |
| (b) Multi-step `RunSettings` / engine chaining | Engine runs target A then target B with explicit artifact handoff | Explicit graph; easier to generalise beyond testgen | Touches engine core; larger protected-path surface; easy to invent a second orchestration language |
| (c) External orchestrator outside the harness | Scripts/CI glue two `eval-harness run` invocations | Zero core change | Splits provenance; Deck B numbers live outside `RunResult`; harder to gate honestly |

**Thesis:** (a) unlocks Deck B with maximum reuse of F-065.
**Counter:** (b) is the "real" product if more scenarios will chain soon.
**Rebuttal:** Ship (a) for testgen only; promote to (b) only when a second scenario proves the pattern. Do not start with (c) — it teaches the organisation that agent metrics live in shell glue.

This package **proposes (a)**; owner confirmation is the gate before implementation estimates.

## Evaluation-design questions (owner before estimate)

1. Prompt held constant across the held-out split, or tuned per item?
2. One generation attempt, or `repetitions` on the generator (now `repetitions: 5` finally measures something)?
3. How is held-out membership enforced mechanically (manifest key, path prefix, config allowlist)?
4. May a `model` target egress under the offline-suite rule for Deck B CI, or only in a credential-gated live workflow?
5. What baseline sits beside the agent (human suite? empty suite? weak corpus slice?) so the slide cannot imply absolute skill?

## Scope / non-goals

- **Non-goal:** publishing agent league tables before a held-out soak distribution exists.
- **Non-goal:** blocking gate thresholds on testgen scorers.
- **Non-goal:** RCA / requirements matrices (separate changes).
- **Non-goal:** production trace ingestion / CHARTER §3 flywheel.
- **Non-goal:** reserving an F-ID in this proposal.

## Impact

- Likely protected paths: `src/eval_harness/targets/**`, possibly `config/**`, root `tests/**`, `features.yaml`, `scripts/validations/**`. Needs `eval-change-approved` at land.
- Must preserve: ADR 0039 allowlist, F-065 scorer purity, matrix freshness gates, offline DI seams.
- Root coverage floor 96% when code lands.

## Success for this docs change

- Proposal + design + tasks + spec checked in.
- Deck A+ notes point here as the Deck B unlock.
- No F-ID reserved; no code shipped in this PR.

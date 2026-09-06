# Tasks: add-agent-in-the-loop-testgen

**Status: proposed (docs only in the introducing PR).** Implementation tasks below are the checklist for the later engineering PR. F-ID claimed at land.

## 0. Owner decisions (hard-stop before coding)

- [ ] 0.1 Confirm option (a) sequential pipeline target, or record a different choice with rationale.
- [ ] 0.2 Answer proposal.md evaluation-design questions (prompt policy, attempts, held-out enforcement, egress, baseline).
- [ ] 0.3 Name whether Deck B CI is offline-only or gains a credential-gated live workflow.

## 1. Spec + ADR

- [ ] 1.1 Land design ADR (claim number at land; mirror ModelTarget / F-065 precedents).
- [ ] 1.2 Keep this change's `specs/agent-in-the-loop-testgen/spec.md` scenarios aligned with validation.

## 2. Implementation

- [ ] 2.1 **[P]** Pipeline `TargetRunner`: generator → suite artifact → `run_generated_suite`.
- [ ] 2.2 **[P]** Explicit `EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST` entry; deny-by-default preserved.
- [ ] 2.3 **[P]** DI seams for generator client; offline fake in tests; no socket in default CI job.
- [ ] 2.4 **[P]** Fail closed when generator returns malformed suite / empty collect.
- [ ] 2.5 **[P]** New opt-in config profile; leave corpus-only `testgen_eval.yaml` behaviour unchanged.
- [ ] 2.6 **[P]** Held-out enforcement test.
- [ ] 2.7 **[P]** Wire existing F-065 scorers only; no new scorer in v1 unless evidence contract gaps appear.
- [ ] 2.8 **[P]** Advisory gate rules only.
- [ ] 2.9 **[P]** Matrix rows only if a new component kind is registered; otherwise regenerate coverage docs if registries change.
- [ ] 2.10 **[P]** `features.yaml` F-ID claimed at land + `scripts/validations/F_0NN.py`.
- [ ] 2.11 Update Deck B estimate in `docs/plans/scenario-eval-matrices/DELIVERY.md` with a real date after 0.x decisions.

## 3. Verification

- [ ] 3.1 `./scripts/quality-gate.sh all` and package checks green.
- [ ] 3.2 Dry-run held-out split; publish distribution, not a single headline mean.
- [ ] 3.3 Record spec-guardian / peer-reviewer passes in `review.md`.

# Tasks: add-agent-in-the-loop-testgen

**Status: landed as F-069 / ADR 0048** (registered `testgen_agent`; not an ADR 0039 allowlist entry). Owner §0 defaults recorded 2026-09-06 in `OWNER_DEFAULTS.md`.

## 0. Owner decisions (hard-stop before coding)

- [x] 0.1 Confirm option (a) sequential pipeline target, or record a different choice with rationale. — **recorded 2026-09-06 in OWNER_DEFAULTS.md (board proceed).**
- [x] 0.2 Answer proposal.md evaluation-design questions (prompt policy, attempts, held-out enforcement, egress, baseline). — **see OWNER_DEFAULTS.md.**
- [x] 0.3 Name whether Deck B CI is offline-only or gains a credential-gated live workflow. — **offline-only CI default; live model only credential-gated.**

## 1. Spec + ADR

- [x] 1.1 Land design ADR (claim number at land; mirror ModelTarget / F-065 precedents). — **ADR 0048.**
- [x] 1.2 Keep this change's `specs/agent-in-the-loop-testgen/spec.md` scenarios aligned with validation. — **Generator Isolation SHALL; in-process `run_generated_suite`.**

## 2. Implementation

- [x] 2.1 **[P]** Pipeline `TargetRunner`: generator → suite artifact → `run_generated_suite`. — **`src/eval_harness/targets/testgen_agent.py`.**
- [x] 2.2 **[P]** Registered name is **not** an ADR 0039 allowlist entry (plan correction). ADR 0039 applies only to optional `generator_path`; deny-by-default preserved; never allowlist `eval_harness`.
- [x] 2.3 **[P]** DI seams for generator client; offline fake in tests (`generate=`); no socket in default CI job.
- [x] 2.4 **[P]** Fail closed when generator returns malformed suite / empty collect (ADR 0038 empty evidence).
- [x] 2.5 **[P]** New opt-in config profile; leave corpus-only `testgen_eval.yaml` behaviour unchanged.
- [x] 2.6 **[P]** Held-out enforcement test (`allowed_splits: [holdout]`; thorough holdout n=11 unique).
- [x] 2.7 **[P]** Wire existing F-065 scorers only; no new scorer in v1.
- [x] 2.8 **[P]** Advisory gate rules only.
- [x] 2.9 **[P]** Matrix rows for the new registered target: M1 / M2 / M3 / M6 plus engine M8; regenerate `docs/matrix-coverage.md`.
- [x] 2.10 **[P]** `features.yaml` F-069 + `scripts/validations/F_069.py`.
- [x] 2.11 Update Deck B estimate in `docs/plans/scenario-eval-matrices/DELIVERY.md` — **coding started 2026-09-08.**

## 3. Verification

- [x] 3.1 `./scripts/quality-gate.sh all` and package checks green.
- [x] 3.2 Dry-run held-out split; publish distribution, not a single headline mean. — **quote thorough holdout n=11 unique; do not quote pass^k from a deterministic fake.**
- [ ] 3.3 Record spec-guardian / peer-reviewer passes in `review.md`.

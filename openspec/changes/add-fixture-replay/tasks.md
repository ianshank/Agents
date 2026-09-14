# Tasks: add-fixture-replay

**Status: F-070 / ADR 0049** (registered `replay` target; not the blocked production flywheel).

## 1. Spec + ADR

- [x] 1.1 Land design ADR 0049 (does not amend CHARTER §3).
- [x] 1.2 Keep `specs/fixture-replay/spec.md` aligned with F-070 verification.

## 2. Implementation

- [x] 2.1 Envelope + `trajectory_from_dict` (strict unknown keys).
- [x] 2.2 JSONL archive confined by DATA_ROOT / OUTPUT_ROOT.
- [x] 2.3 Registered `replay` TargetRunner: exact | counterfactual; `run` takes only `item`.
- [x] 2.4 Slice pass-rates + first `tool_error` report (CLI/HTML).
- [x] 2.5 `eval-harness replay` dispatched without growing `engine.py` / `comparison.py`.
- [x] 2.6 Matrix rows M1/M2/M3/M6; regenerate `docs/matrix-coverage.md`.
- [x] 2.7 `features.yaml` F-070 + `scripts/validations/F_070.py`.
- [x] 2.8 Demo beat 6 with committed fixtures; README claims only shipped commands.
- [x] 2.9 Answer-quality corpus + advisory config (reuse `req_scope_hallucination` + `trajectory_recovery`).
- [x] 2.10 `experiments/trace-analytics/` SQL sketches; ClickHouse/production ingest stay gated.

## 3. Verification

- [ ] 3.1 `./scripts/quality-gate.sh all` green.
- [x] 3.2 Record that this change does **not** archive or unblock `add-production-eval-flywheel`.

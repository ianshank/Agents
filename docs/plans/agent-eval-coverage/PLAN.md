# Implementation Plan — Agent-Evaluation Coverage

**ID:** PLAN-2026-08-05-agent-eval-coverage
**Date:** 2026-08-05 · **Base commit:** `b52c696` (merge of PR #118)
**Motivated by:** `./REVIEW.md` — peer review of an external coverage analysis and its proposed
five-change implementation plan. Roughly a third of the analysis's coverage matrix was refuted
against the tree; three of the five proposed changes would have failed CI as written.
**Scope:** close the three confirmed gaps in agent evaluation — trajectory, repeated-run
reliability, environment state — plus judge bias calibration and an offline production-trace loop.
**Non-goals:** benchmark adapters (SWE-bench, τ-bench, BFCL) pending a separate scope decision;
runtime guardrails; live evaluation in merge CI.

---

## Cross-cutting standards

| Standard | Rule | Source of truth |
|---|---|---|
| Core-model changes | Additive only, under ADR 0031's six obligations: append-only fields, no freezing of existing types, `SCHEMA_VERSION` untouched, `to_dict()` omits absent keys, surface baselines regenerated in the same change, default-off behaviour | [ADR 0031](../../decisions/0031-additive-core-model-extension-for-agent-evaluation.md) |
| Airgap | `eval_harness ⇎ flow_corpus` stays severed. Shared calibration math goes in `agent_core`, consumed via `agent_core_adapter`. `architecture.yaml` is not edited to permit a new edge | `architecture.yaml`, F-011/F-012 |
| Config | New fields optional with behaviour-preserving defaults; extend `GateRule.metric`, never add a parallel `gates:` block — `from_dict` is strict and unknown keys raise | `src/eval_harness/config/models.py:156-171`, CHARTER §3 |
| Skipped scorers | `passed=None` + comment. No `not_applicable` status enum | `scorers/__init__.py:301-308` |
| File size | Hard fail above 500 lines. New scorers land in their own module, imported for registration only | `scripts/check_size_budget.py:45` |
| Baselines | Every new export and every new registered name requires `python tests/test_public_surface.py --update`; both baseline JSONs are protected paths | F-039 |
| Coverage floors | root/`eval_harness` 96; `agent-core` 95. New code states the floor of where it lands | `pyproject.toml:162` |
| Feature pattern | `features.yaml` entry + `scripts/validations/F_0NN.py` + ADR when architectural. **Next free ID: F-051.** Next ADR after 0031: 0032 | `features.yaml`, `docs/decisions/` |
| Protected paths | `scorers/`, `judges/`, `gating/`, `tests/**`, `config/**`, `features.yaml`, `scripts/validations/**`, `.github/**`, `architecture.yaml` need the `eval-change-approved` label + CODEOWNERS review | `scripts/eval_protected_paths.py` |

---

## Phase 0 — Escalation (complete)

- `./REVIEW.md` — peer review with the corrected coverage matrix.
- [ADR 0031](../../decisions/0031-additive-core-model-extension-for-agent-evaluation.md) — authorises
  the additive core-model and engine-loop extension; explicitly does **not** amend the airgap.
- `docs/CHARTER.md` — §3 Ratified Amendment entry plus the §4 invariant-1 exception clause. Both
  charter gates green.

## Phase 1 — Five OpenSpec change packages (proposals only)

Under `openspec/changes/<id>/{proposal,design,tasks,review}.md` + `specs/<capability>/spec.md`:

| Order | Change ID | Capability |
|---|---|---|
| 1 | `add-agent-trajectory-evaluation` | Trajectory data model and matching scorers |
| 2 | `add-repeat-reliability-metrics` | Repeated execution, pass@k, pass^k, distributions |
| 3 | `add-stateful-outcome-evaluation` | Assert on environment state rather than output text |
| 4 | `extend-judge-calibration` | Order/verbosity/self-preference bias probes |
| 5 | `add-production-eval-flywheel` | Trace ingestion, incident promotion, regression gating |

Ordering rationale (carried unchanged from the reviewed plan, which got this right): measurement
primitives first, then reliability, then real-world state validation, and only afterwards the
production feedback loop. Change 5 additionally requires its own charter amendment before its
proposal is accepted (REVIEW §B13).

## Phase 2 — Implement Change 1 (F-051)

| Area | Files | Protected |
|---|---|---|
| Contracts | `core/types.py`, `core/__init__.py` | no |
| Normalisation | new `core/_trajectory.py` (pure — no I/O, charter §4 invariant 4) | no |
| Serialisation | `RunResult.to_dict()` — emit `trajectory` only when present | no |
| Scorers | new `scorers/trajectory.py`; `scorers/__init__.py` imports it for registration | **yes** |
| Sinks | `json_file` via `to_dict`; `html_file` summary keeps its pure-function property | no |
| Tests | root suite at the 96% floor | **yes** |
| Baselines | `tests/public_surface_baseline.json`, `tests/plugin_registry_baseline.json` | **yes** |
| Governance | `features.yaml` F-051, `scripts/validations/F_051.py`, `architecture.yaml`/`.mmd`, CHANGELOG, docs | **yes** |

Registered scorer names: `trajectory_exact`, `trajectory_in_order`, `trajectory_any_order`,
`trajectory_precision_recall`, `trajectory_step_efficiency`, `trajectory_loop_detection`,
`trajectory_recovery`.

**PR split by protection level:** (1) unprotected contracts, normalisation, sinks, docs;
(2) protected scorers, tests, baselines; (3) protected `features.yaml`, validation script,
architecture manifest. PRs 2 and 3 need the `eval-change-approved` label.

## Verification

```bash
./scripts/quality-gate.sh lint
./scripts/quality-gate.sh typecheck
./scripts/quality-gate.sh coverage          # COV_FAIL_UNDER=96
python scripts/check_size_budget.py
python scripts/check_charter_drift.py
python scripts/check_charter_invariants.py
python scripts/validate.py --tier fast
python scripts/validations/F_051.py
make check-all
```

Behavioural acceptance, asserted by tests rather than inspection:

- a two-tool-call target round-trips `TargetOutput` → `to_dict()` → JSON in execution order, with
  `error` and `latency_ms` intact;
- a text-only target leaves every pre-existing scorer's output unchanged and emits no `trajectory`
  key;
- exact matching fails and in-order matching passes on the same `A, X, B` candidate;
- any-order matching passes on `B, A` against reference `A, B`;
- a candidate that repeats one required call and omits another reports reduced precision **and**
  reduced recall as separate numbers;
- a fourteen-step success against a four-step budget passes the outcome scorer while step efficiency
  reports the excess;
- an agent proceeding as though a failed tool call succeeded fails the recovery scorer;
- historical positional `TargetOutput(output, latency_ms, error, metadata)` construction still works;
- both baseline JSONs diff only by the intended additions.

## Delivery order after this branch

Changes 2 → 3 → 4 → 5, each as its own vertical slice: contract → unit tests → implementation →
registration → serialisation → documentation → executable F-ID proof.

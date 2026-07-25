# Implementation Plan — Agent-Record Calibration: First Honest Report (v2, post-review)

**ID:** PLAN-2026-07-24-agent-record-decontamination-v2
**Date:** 2026-07-24 · **Base commit:** `961cfd14` (merge of PR #79)
**Supersedes:** the same-day draft; peer-review corrections in `REVIEW.md` (this directory)
are incorporated throughout. Narrows the soak-endgame record counting of
PLAN-2026-07-03-agents-foundation-extraction-soak-v2 Phase 3 ("N≥20 + ≥1 human verdict",
`../agents-critical-path/PLAN.md`) and `../real-data-activation/PLAN.md` step 6: milestones
are henceforth stated over **agent-domain** records — a tightening ("never lower N
silently" holds), recorded in ADR 0026.
**Scope:** Milestone redefinition + F-044 backfill decision (ADR 0026) → confidence-lane
consistency → first human-audit verdicts through the existing machinery → fit-time
degeneracy guards + first committed agent-records calibration report →
calibrated-confidence decision point.
**Non-goals:** tau enablement / auto-merge activation (`min_calibration_n=200` and the
ADR 0005 checklist untouched); Braintrust work (F-038 done; managed prompts tracked
separately); external replication before its evidence is committed in-repo; `experiments/`
deletion.

---

## Cross-cutting standards

| Standard | Rule | Source of truth |
|---|---|---|
| Store ground truth | The store moves daily (labeller cron 05:17 UTC). Every committed figure carries a measured-at timestamp and the `merge-gate-data` SHA; every phase re-measures at start. | `.github/workflows/outcome-labeller.yml`, ADR 0018 |
| Config discipline | Tunables are frozen `*Config` dataclass fields; `agent_core` stays config-file-free. No YAML knobs for calibration math. | `AGENTS.md`, `agent-core/agent_core/domains.py` |
| Label model | `LabelSource` = REVERT, CI_FAILURE, TIMEOUT_CLEAN (passive) + HUMAN_AUDIT (authoritative). Tau/health fit from HUMAN_AUDIT only via the tested silent filter; passive labels are diagnostics; `timeout_clean` is optimistic by construction (fail-safe detectors). | `agent-core/agent_core/outcome_store.py:157-199`, `agent-core/tests/test_outcome_store.py:195-198`, `agent-core/agent_core/outcome_labeller.py:99-101` |
| ID assignment | ADR 0026 is next-free (0025 was consumed the same day by the outcome-record forward-compatibility decision -- a live instance of the drift this row warns about; re-verify at authoring). F-numbers are claimed by the implementation PR that lands them (next free today: F-047), never reserved in plans — every ID the 07-03 plan pre-assigned (F-038/F-039/F-040, ADR 0019/0020) drifted or gapped. | `../../decisions/README.md`, `features.yaml` |
| Protected paths | Phase 1 and Phase 3 implementation PRs touch `.github/**` / root `tests/**` / `scripts/validations/**` → each needs `eval-change-approved` before merge (the guard re-runs on label events). Phase 0 (docs) and Phase 2 (zero code) need none. | `scripts/eval_protected_paths.py` |
| Report views | PRIMARY (HUMAN_AUDIT-only, tau-relevant) is never pooled with DIAGNOSTIC (includes weak `timeout_clean`). | F-043, `agent-core/agent_core/calibration_report.py:266-285` |

---

## Phase 0 — Agent-record milestone + backfill decision (ADR 0026; P0, docs only, same day)

Measured state (store @ `39b3c22`, latest `merged_at` 2026-07-24T18:08:21-04:00): 43
records / 31 change_ids; 5 agent-domain rows (`claude-code`), 4 distinct confidences; 8
`timeout_clean` + 4 `ci_failure`; **0 `human_audit`** ⇒ tau `None` everywhere.

1. Author **ADR 0026** (`docs/decisions/0026-agent-record-calibration-milestone.md`),
   bundling (precedent: ADR 0023 bundles four decisions):
   - **Reporting milestone:** N≥20 agent-domain records with ≥3 distinct `raw_confidence`
     values and both label classes present among agent rows. Reporting-only — tau floors
     (`min_calibration_n=200`, `is_trustworthy`) and the ADR 0005 checklist untouched.
   - **Acting-gate posture:** the acting gate's confidence-blindness
     (`.github/workflows/calibrated-merge-gate.yml:52-53`) is declared intentional while
     `ENABLE_CALIBRATED_AUTOMERGE` stays off; revisit at enablement-checklist time.
   - **Fit-guard posture:** opt-in `FitGuardConfig` (Phase 3); dataclass fields, no YAML.
   - **Decision-point criterion:** K=15 audited agent rows; AUROC bar = `min_auroc`
     (0.65).
   - **F-044 backfill disposition:** run the landed-but-never-applied
     `scripts/migrations/agent_domain_backfill.py` against the live store (dry-run first;
     converts the ~18 historical Claude-authored `human/*` rows to agent domains, taking
     the agent-domain count from ≈5 to ≈23) — or record why not. Run-state verified
     2026-07-24: those rows are still `human/*`; the sole pre-07-23 agent row is PR #73's
     real-time self-seed, not backfill output.
2. Add the index row in `../../decisions/README.md` (the 0007 gap stays).

**Exit gate:** ADR 0026 merged; the milestone can no longer be satisfied by `human/*`
rows; backfill decision executed with its store SHA recorded.
**Files:** `docs/decisions/0026-agent-record-calibration-milestone.md` (new),
`docs/decisions/README.md`.

---

## Phase 1 — Confidence-lane consistency (F claimed at land; ~half day + review)

1. **Shadow-lane classification.** The shadow job composes context with neither
   `--confidence` nor `--human` (`.github/workflows/calibrated-merge-gate.yml:141`),
   silently producing un-prefixed agent domains at 0.0 via
   `scripts/merge_gate_context.py:135`. Fix: classify `github.head_ref` against
   `config/agent-authors.yaml` via `scripts/agent_confidence.py` (mirrors the seed lane;
   no API call needed on `pull_request` events): agent → `--confidence <proxy>`, else
   `--human`.
2. **Fail loud.** `scripts/merge_gate_context.py` exits 2 when neither flag is given,
   closing the :135 leak (after step 1 no caller relies on it). Update root
   `tests/test_merge_gate_context.py`.
3. **No acting-gate wiring** — covered by ADR 0026 (acting-gate posture).
4. **Elicited self-reported confidence:** design sketch only, deferred behind the Phase 4
   decision point. The proxy is the baseline; a second signal must beat it on audited
   data before earning plumbing.
5. `config/agent-authors.yaml` grows only when a new agent family's PRs are actually
   observed.
6. Update workflow-content pins in `scripts/validations/F_035.py` / `F_042.py` if the
   workflow edit trips them; claim the next free F-number (`features.yaml` +
   `scripts/validations/F_0XX.py`).

**Exit gate:** a `claude/*` PR's shadow summary shows the agent lane with nonzero proxy
confidence; neither-flag invocation fails with exit 2; validations green;
`eval-change-approved` obtained before merge.
**Files:** `.github/workflows/calibrated-merge-gate.yml`, `scripts/merge_gate_context.py`,
`tests/test_merge_gate_context.py`, `scripts/validations/*`, `features.yaml`.

---

## Phase 2 — First human-audit verdicts (zero code; ~1-2 h operator time across 1-2 weeks)

The chain is fully implemented and has never been exercised; this phase runs it and writes
nothing new.

1. Trigger `merge-gate-audit.yml` selection (workflow_dispatch, or consume the next Monday
   06:23 UTC cron run). At today's N the per-domain floor (`MERGE_GATE_AUDIT_FLOOR=3`)
   dominates the 5% rate — agent domains will be sampled.
2. Record **10-15 verdicts** via `merge-gate-verdict.yml` (workflow_dispatch; the sole
   HUMAN_AUDIT writer; auditor allowlist + environment), prioritizing (a) every
   agent-domain row, (b) the known `ci_failure` rows — the audited set needs a chance at
   both classes; verdicts on merged changes will skew "correct" and a single-class outcome
   may not be forceable.
3. If the audited set stays single-class, that is reported honestly (the report already
   marks single-class slices DEGENERATE) and Phase 4 waits.

**Exit gate:** ≥10 `label_source == "human_audit"` rows including ≥5 agent-domain rows
(re-measure; agent rows accrue with every merged `claude/*` PR, plus the backfill if run);
a single-class outcome documented if it happens.

---

## Phase 3 — Fit-time guards + first committed report (F claimed at land; ~1 day)

1. **Opt-in `FitGuardConfig`** in `agent-core/agent_core/calibration.py`: frozen
   dataclass, fields `min_fit_samples: int | None = None`,
   `refuse_constant: bool = False`; enforced in `IsotonicCalibrator.fit` only when set.
   Default-`None` call sites stay byte-identical — the cold-start empty-fold fallback
   (`agent-core/agent_core/outcome_store.py:173-174`) and its locking test
   (`agent-core/tests/test_outcome_store.py:185-192`) keep fitting N=1 by design
   (ADR 0023 I-2: no TCB semantic change). `calibration_report` threads guards from
   `ReportConfig` for report-path fits.
2. **Single-class honesty:** document or tighten `evaluate_calibration`'s AUROC
   pass-through (`agent-core/agent_core/calibration.py:321-325` — `roc is None` currently
   satisfies the criterion).
3. **First committed snapshot:** `docs/calibration-agent-records-2026-MM.md` in the
   gap-analysis idiom — dated measured prose + embedded `calibration_report` output (both
   views) + store SHA + measured-at. Not baseline-JSON (wrong for a daily-moving store);
   the ephemeral live view stays in the labeller step summary. Include the honesty
   statement: at n≈12 audited records, Wilson half-widths are ≈±0.2-0.3 — a baseline, not
   a verdict.
4. Tests to the agent-core 95 floor; F-entry + `scripts/validations/F_0XX.py`; CHANGELOG
   entry (user-visible artifact).

**Exit gate:** agent-core gate green; guards verified opt-in (existing call sites
byte-identical); snapshot committed and linked; `eval-change-approved` obtained.
**Files:** `agent-core/agent_core/calibration.py`,
`agent-core/agent_core/calibration_report.py`, `agent-core/tests/*`,
`docs/calibration-agent-records-*.md` (new), `features.yaml`, `scripts/validations/*`,
`CHANGELOG.md`.

---

## Phase 4 — Calibrated-confidence decision point (clock-gated on ≥15 audited agent rows)

On the audited agent subset: if neither the proxy nor (if built by then) an elicited
signal clears `min_auroc = 0.65`, the calibrated-confidence thesis re-scopes to the gate's
existing Wilson-floor-on-outcomes path — recorded as a new ADR (next free number at that
time). Either outcome is publishable. The proxy is the baseline being tested, not the
fallback: the draft's kill criterion assumed self-reported confidence was the plan of
record and mechanical signals the pivot; ADR 0023 shipped the reverse.

---

## Explicitly deferred / evidence-gated

- **External replication (GABench failure taxonomy, WML repo review):** no phase until
  the 2026-07-24 scan notes are committed under `docs/` — nothing in-repo currently
  evidences them.
- **Braintrust:** nothing to defer — F-038 shipped (additive, off by default); managed
  prompts remain deferred on their own record (`../../braintrust-spike.md`).
- **`experiments/` audit:** after Phase 3; corrected figures 7,444 Python lines (4,282
  non-test); it is D-0 (Langfuse-vs-Opik) evidence infrastructure with pending human
  steps, not deletion-ready.
- **SpecKit-vs-OpenSpec bake-off:** dropped — no in-repo trace exists to be "unchanged"
  relative to.

## Sequencing

```
P0 (ADR 0026 + backfill, same day) ──► P1 (lane consistency) ──────► P3 (guards + report)
        └────────────► P2 (audit verdicts; independent, human-paced) ──┘
P3 + ≥15 audited agent rows ──► P4 decision point (new ADR)
External replication: no phase until scan notes are committed in-repo
```

## Risk register

| Risk | Mitigation |
|---|---|
| Store drift between planning and execution | Re-measure at each phase start; every committed figure stamped measured-at + store SHA |
| Protected-path guard blocks P1/P3 | Request `eval-change-approved` up front; the guard re-runs on label events |
| Audited subset stays single-class | Report marks it DEGENERATE honestly; audit floor pulls `ci_failure` rows in; P4 stays clock-gated |
| Fit guards break cold-start semantics | Opt-in `None` defaults; existing call sites byte-identical; fold-fallback test locks it |
| ID pre-assignment drift | Only ADR 0026 named (authored same day in P0); F-numbers claimed at land — the F-040 gap is the precedent |
| Backfill double-run or audit-row rewrite | Migration refuses audit-row rewrites (`scripts/migrations/agent_domain_backfill.py:99-100`); dry-run first; run-state verified before the ADR |
| Elicited signal would recreate a constant predictor | Distinctness check before any calibrator sees it; comparison confined to the audited subset |
| Snapshot mistaken for live state | Dated filename + measured-at header + pointer to the ephemeral live view |

## Acceptance summary

- ADR 0026 accepted: agent-record reporting milestone (unsatisfiable by `human/*` rows),
  acting-gate posture, fit-guard posture, decision-point criterion, backfill disposition —
  tau floors untouched
- Backfill decision executed with recorded store SHA (expected: agent rows ≈5 → ≈23)
- Shadow lane routes like the seed lane; neither-flag invocation fails loud
- ≥10 HUMAN_AUDIT verdicts including ≥5 agent-domain rows through the
  previously-unexercised audit chain
- Opt-in fit guards merged with locking tests; single-class AUROC pass-through documented
  or tightened
- First committed dated agent-records calibration report (PRIMARY + DIAGNOSTIC, Wilson
  CIs, honesty statement)
- Phantom work items corrected in the record: no Braintrust migration pending,
  `experiments/` figures fixed, SpecKit/OpenSpec dropped, external replication
  evidence-gated

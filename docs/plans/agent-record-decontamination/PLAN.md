# Implementation Plan — Agent-Record Calibration: First Honest Report (v3, post-review)

**ID:** PLAN-2026-08-06-agent-record-calibration-v3
**Date:** 2026-08-06 · **Base commit:** `f565e08` (merge of PR #122)
**Supersedes:** v2 (`PLAN-2026-07-24-agent-record-decontamination-v2`), merged in PR #80;
peer-review corrections in `REVIEW-v2.md` (this directory) are incorporated throughout. v2
remained accurate for about a day; 82 commits later four of its claims no longer hold.
**Scope:** F-044 backfill disposition → shadow-lane confidence consistency → first
human-audit verdicts through the existing machinery → first committed agent-records
calibration report → the calibrated-confidence decision point, now measurable.
**Non-goals:** `tau` enablement / auto-merge activation (ADR 0005 checklist untouched);
changing `risk_target` or `wilson_floor` — ADR 0026 rules those a risk-appetite decision
needing their own ADR; the milestone redefinition v2 proposed, which **ADR 0026 has already
settled**; external replication; `experiments/` deletion.

---

## Cross-cutting standards

| Standard | Rule | Source of truth |
|---|---|---|
| Store ground truth | The store moves daily (labeller cron 05:17 UTC). Every committed figure carries a measured-at stamp and the `merge-gate-data` SHA; every phase re-measures before it acts. This is the standard that caught v2's drift. | `.github/workflows/outcome-labeller.yml`, ADR 0018 |
| **Reserve no identifiers** | Never pre-assign an ADR or F-number. v2's own table said so and v2 then reserved ADR 0026, which was taken the next day (`REVIEW-v2.md` finding 1); the 07-03 plan's F-040 gap took a month to close. Measured 2026-08-06: next free ADR **0032**, next free **F-052** — re-verify at authoring, cite nothing until claimed. | `../../decisions/README.md`, `features.yaml` |
| Config discipline | Tunables are frozen `*Config` dataclass fields, validated in `__post_init__`, and reachable from the CLI by defaulting the flag off the dataclass. `GatePolicyConfig` now models this fully. | `AGENTS.md`, `agent-core/agent_core/merge_gate.py` |
| Label model | `LabelSource` = REVERT, CI_FAILURE, TIMEOUT_CLEAN (passive) + HUMAN_AUDIT (authoritative). Tau/health fit from HUMAN_AUDIT only; passive labels are diagnostics, and `timeout_clean` is optimistic by construction. | `agent-core/agent_core/outcome_store.py` (filter at :307), `agent-core/tests/test_outcome_store.py:298` |
| Estimator boundary | Wilson is the gate's only estimator. PPI++ is report-only and fail-closed; nothing on an auto-merge path may import it. | ADR 0026 |
| Protected paths | Phase 1 touches `.github/**` and root `tests/**` → its own PR, with `eval-change-approved`. Phases 0, 2 and 3 as scoped need none. | `scripts/eval_protected_paths.py` |

---

## Measured state (store `4c07d7e`, measured 2026-08-06; latest `merged_at` 2026-08-05)

| | |
|---|---|
| Total | 83 rows / 46 change_ids |
| Agent-domain | **24 rows / 15 change_ids** (was 5/5 on 07-24 — organic growth, no backfill) |
| Agent `raw_confidence` | 4 distinct: 0.02, 0.024844, 0.05643, 0.724122 |
| Agent labels | `timeout_clean` ×9, unlabelled ×15 — **no failure class** |
| `human_audit` | **0** ⇒ `tau is None` in every domain |
| All labels | `timeout_clean` ×32, `ci_failure` ×5, unlabelled ×46 |

---

## Phase 0 — Close the F-044 backfill decision (docs only; ~half day)

v2 left this open ("run it — or record why not"). The evidence now answers it, and an
open-ended disposition on a production-data migration is itself a liability.

**Decision to record: do not run it.** Four independent reasons:
1. Its stated purpose — crossing N≥20 agent records — is **already met organically** (24).
2. ADR 0026 reframed that target as a soak counter, not a gate, so the thing it aimed at is
   not a decision threshold at all.
3. It cannot supply what is missing. The gaps are a failure class among agent rows and
   `human_audit` anywhere; re-attributing a domain creates neither.
4. It mutates append-only production data on `merge-gate-data` for historical tidiness,
   against an audit trail whose value is that it is not rewritten.

Write it as an ADR (next free at authoring), following the `0026`/`0029` shape:
Status/Date/Related, Context, Decision, Consequences, explicit reversibility. State the
condition that would reopen it — a future need to key historical records by
`(agent_version, domain)` for cross-cell analysis, which ADR 0026 defers until ≥3 populated
cells exist. Add the index row in `../../decisions/README.md`; the intentional `0007` gap
stays.

**Exit gate:** ADR merged; `scripts/migrations/agent_domain_backfill.py` either deleted or
carrying a header pointing at it, so the next reader does not rediscover an unrun migration
with no verdict.
**Files:** `docs/decisions/00XX-*.md` (new), `docs/decisions/README.md`.

---

## Phase 1 — Shadow-lane confidence consistency (own PR, `eval-change-approved`; ~half day)

Re-verified live at `f565e08`: `.github/workflows/calibrated-merge-gate.yml:141` composes
context with **neither** `--confidence` nor `--human`, so every shadow decision records an
un-prefixed agent domain at confidence 0.0 — the un-prefixed lane is the *agent* lane, so
this mislabels human PRs as agent ones at zero confidence.

1. Classify `github.head_ref` against `config/agent-authors.yaml` via
   `scripts/agent_confidence.py` — mirrors the seed lane and needs no API call on
   `pull_request` events: agent → `--confidence <proxy>`, else `--human`.
2. Make `scripts/merge_gate_context.py` exit 2 when neither flag is given, closing the
   silent-default path once no caller relies on it. Re-derive the line number first.
3. Update root `tests/test_merge_gate_context.py`; refresh any workflow-content pin in
   `scripts/validations/`; claim the F-number at land time.

**Exit gate:** a `claude/*` PR's shadow summary shows the agent lane at nonzero proxy
confidence, a human PR shows `human/*` at 0.0, and a neither-flag invocation fails instead
of defaulting.
**Files:** `.github/workflows/calibrated-merge-gate.yml`, `scripts/merge_gate_context.py`,
`tests/test_merge_gate_context.py`, `scripts/validations/*`, `features.yaml`.

---

## Phase 2 — First human-audit verdicts (zero code; operator-gated)

Unchanged from v2 and still the critical path: this is the only reason `tau` is `None`
everywhere. The chain is fully built and has still never been exercised.

1. Trigger `merge-gate-audit.yml` selection (dispatch, or the Monday 06:23 UTC cron). Select
   `--with-propensity` so `selection_propensity` is captured **during** the round — ADR 0026
   is explicit that it cannot be reconstructed afterwards.
2. Record verdicts via `merge-gate-verdict.yml` (dispatch-only; the sole HUMAN_AUDIT writer).
   Prioritise agent-domain rows, and include `ci_failure` rows so the audited set has any
   chance at both classes.
3. If it stays single-class, report that honestly — the report already marks such a slice
   DEGENERATE — and let Phase 4 wait rather than forcing a verdict.

**Exit gate:** ≥10 `human_audit` rows including ≥5 agent-domain, each with a recorded
propensity. Re-measure; agent rows accrue with every merged `claude/*` PR.

---

## Phase 3 — First committed agent-records calibration report (~half day)

The guard work v2 scoped here **shipped in PR #80** (`CalibrationConfig.min_eval_samples` /
`require_discrimination`), and the degeneracy machinery is richer than v2 anticipated. What
remains is the deliverable itself, which still does not exist.

1. Run `agent_core.calibration_report` over the agent slice with `--estimator wilson`
   (default), and render the PPI++ column alongside it as ADR 0026 intends — report-only.
2. Commit it as `docs/calibration-agent-records-<YYYY-MM>.md` in the gap-analysis idiom:
   dated measured prose, embedded output, store SHA, measured-at.
3. State the honest width. At the audit counts Phase 2 can realistically produce, Wilson
   half-widths sit around ±0.2-0.3; the document is a baseline, not a verdict, and should
   say so in its opening line.
4. Optional, cheap, and worth folding in: **G4** — four CLIs (`calibration_report`,
   `merge_seed`, `outcome_labeller`, `audit_sampler`) log their only structured run record at
   INFO but never call `configure_logging`, so it is discarded. One line each; none can
   change a gate decision.

**Exit gate:** report committed and linked from `docs/README.md`; agent-core gate green.

---

## Phase 4 — Calibrated-confidence decision point (clock-gated on Phase 2)

Now concrete rather than hypothetical. Use `agent_core.proxy_eval` to measure proxy↔audit
correlation **marginally and conditionally** (on `score >= candidate tau`, and per bin). Per
ADR 0026 the difference between those rows is the finding: a marginal number alone
recommends the wrong lever.

Decision: if no proxy clears `min_auroc` (0.65) on the audited agent subset, the
calibrated-confidence thesis re-scopes to Wilson-floor-on-outcomes, and the orthogonal
`passive_label` proxy — which ADR 0026 measured at 1.63× effective-N against
`raw_confidence`'s 1.08× — becomes the candidate worth building. Either outcome is
publishable; record it as an ADR at that time.

---

## Sequencing

```
P0 (backfill verdict, docs) ──────────────────────────────► P3 (first report)
P1 (shadow lane, own PR + label) ─────────────────────────► P3
P2 (audit verdicts; operator-paced, the critical path) ───► P3 ──► P4 (needs P2's audits)
```

## Risk register

| Risk | Mitigation |
|---|---|
| Plan drifts again between authoring and execution | Re-measure at every phase start and stamp the store SHA; that rule is what caught v2 |
| An identifier is reserved and then taken | Reserve none; claim at land time (`REVIEW-v2.md` finding 1) |
| Audited subset stays single-class | Report DEGENERATE honestly; pull `ci_failure` rows into the sample; P4 waits rather than forcing a number |
| Phase 1 stalls on the protected-path label | Keep it in its own PR so Phases 0/3 are not blocked behind it |
| PPI++ mistaken for a gate estimator | Wilson stays the gate's only estimator; the report column is labelled report-only (ADR 0026, pinned by its validation script) |
| Propensity lost | Phase 2 selects `--with-propensity`; it is unreconstructable after the round |

## Acceptance summary

- Backfill disposition recorded as an ADR, with its reopening condition — no longer an open
  question against production data
- Shadow lane routes like the seed lane; neither-flag invocation fails loud
- ≥10 HUMAN_AUDIT verdicts incl. ≥5 agent-domain, each carrying a propensity
- First committed dated agent-records calibration report, honest about its width
- Decision point answered with a measured ρ, marginal and conditional, or explicitly still
  waiting on audits
- No identifier reserved anywhere in this document

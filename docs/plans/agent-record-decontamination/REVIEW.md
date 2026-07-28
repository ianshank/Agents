# Peer Review — Agent-Record Decontamination Plan (2026-07-24 draft)

**Reviewed artifact:** PLAN-2026-07-24-agent-record-decontamination (draft; never committed)
**Method:** three independent read-only verification passes against the working tree at
`961cfd14` (merge of PR #79) and the live `merge-gate-data` store (`39b3c22`, latest
`merged_at` 2026-07-24T18:08:21-04:00), plus a synthesis pass. Every falsifiable claim in
the draft was classified CONFIRMED / PARTIALLY TRUE / REFUTED with file:line evidence.
**Outcome:** the corrected plan is `PLAN.md` in this directory (v2). The draft is superseded.

## Verdict

Right instinct, stale evidence, ~16 factual errors. The draft correctly identifies the two
scarce resources — agent-domain records and human-audit labels — and its constant-predictor
mathematics is sound. But its "[Certain]" ground truth is ADR 0023's committed 2026-07-22
measurement recycled after the remediation shipped (F-042/F-043/F-044/F-046 landed
2026-07-22/23 via PRs #73/#75): P1 proposes machinery that already exists behind a
different seam, P2's acceptance criterion tests a guard that has never existed, P4 rests on
evidence absent from the repository, and the kill criterion pivots *to* the baseline that
already shipped. The phase spine survives after inverting P1 and the kill criterion; the
human-audit bottleneck it names is real and is now the critical path.

## Findings that would break execution

1. **The central premise is stale — REFUTED.** "The gate built to calibrate agents has never
   seen an agent" was true on the morning of 2026-07-22 and is false now. The live store
   holds **43 records / 31 change_ids**, including **5 `agent_version: "claude-code"` rows**
   in un-prefixed agent domains (`agent-core` ×3, `eval-harness` ×2) carrying four distinct
   `raw_confidence` values (0.0, 0.02, 0.024844, 0.724122). The draft's exact figures — 34
   records / 25 change_ids, every row `human/*` at 0.0 — are
   `docs/decisions/0023-agent-confidence-proxy-and-agent-domain-seeding.md:14` verbatim;
   the claimed "2026-07-24 external audit" reproduced a committed measurement, not the
   store. The first agent-routed record is PR #73's own merge (`0ffd0379`, store commit
   `b9747c6`, 2026-07-22T06:14 EDT) — the remediation PR seeded itself minutes after that
   measurement was taken.

2. **P1 targets the wrong seam — REFUTED.** `merge_gate_ci.py --agent-version`
   (`agent-core/agent_core/merge_gate_ci.py:124`) is inert unless `--seed-store` and
   `--change-id` are passed *and* the decision is AUTO_MERGE (:134-142) — and no workflow
   passes `--seed-store`. Production seeding runs out-of-band in
   `.github/workflows/merge-gate-seed.yml:116-127` via `agent_core.merge_seed`, which since
   F-042 already routes agent PRs by head-branch prefix (`config/agent-authors.yaml`) with
   a deterministic proxy confidence (`scripts/agent_confidence.py:194-220`,
   `config/agent-confidence.yaml`). "Run agent PRs through `merge_gate_ci.py`" would build
   a second, redundant lane.

3. **P2's acceptance criterion tests a guard that does not exist — REFUTED.** There is no
   "runtime guard rejecting mechanical labels from the fit"; the restriction is a *silent
   filter* (`agent-core/agent_core/outcome_store.py:166-169`), already tested as silent
   exclusion (`agent-core/tests/test_outcome_store.py:195-198`,
   `test_build_models_ignores_passive_labels`, asserting `== {}`). No raise path exists
   anywhere for a test to exercise. The v2 keeps the filter semantics and drops the
   phantom guard.

4. **The target path and "plan register" do not exist — REFUTED.** No root `PLAN-*.md` has
   ever existed; "PLAN-2026-07-03-agents-foundation-extraction-soak" is the `**ID:**` field
   of `../agents-critical-path/PLAN.md` (line 3, with a `-v2` suffix). House convention is
   `docs/plans/<topic>/{PLAN.md,REVIEW.md}` (`../../STYLE.md`, `../../README.md` § Plans).
   No plan register exists; the ADR index (`../../decisions/README.md`) is the repo's only
   registered-artifact pattern.

5. **The Braintrust deferral defers nothing — REFUTED.** There is no pending "Braintrust
   migration": F-038 shipped it as an additive, reversible, SDK-optional, off-by-default
   spike (`features.yaml:673`, `../../braintrust-spike.md`). "D-0" is the
   *Langfuse-vs-Opik* displacement decision inside `experiments/backend-validation` (TCB
   unsigned, probes never run) — unrelated to Braintrust — and "SDK spike" matches nothing
   in the repo.

6. **P4's evidence base is absent from the repository — REFUTED as stated.** GABench, WML,
   the "verified 07-24 arXiv scan", and the SpecKit-vs-OpenSpec bake-off have zero
   occurrences across the working tree, every blob reachable from all git refs, and all
   commit messages. A phase cannot cite evidence the repo does not hold; v2 gates the
   external track on committing the scan notes first.

7. **The kill criterion pivots to the shipped baseline — REFUTED premise.** The pivot
   destination ("calibrating mechanical signals: diff size, test-delta, path risk") is
   precisely the F-042 proxy already in production: a clamped sigmoid over diff size,
   files touched, test ratio, and protected-path contact. The open question is the reverse
   one — whether *self-reported* confidence ever adds discrimination over the mechanical
   baseline. v2 restates the decision point accordingly.

## Wrong standards that would have propagated

8. **"Committed the way STATUS pins coverage" — no STATUS file exists.** The repo's pin
   idioms are `fail_under` in `pyproject.toml` (96/95/85), committed exact-equality
   `*_baseline.json` files (F-039), and dated measured-prose snapshots
   (`../../gap-analysis-2026-07.md`). v2 uses the dated-prose idiom — a baseline JSON
   would be wrong for a store that changes daily.

9. **"Adopt Edge-DIT's `min_fit_samples` pattern; config value, not literal" — wrong on
   both ends.** Edge-DIT has zero in-repo occurrences, and the house rule places tunables
   in frozen `*Config` dataclass fields (`AGENTS.md:81`) — `agent_core` is deliberately
   config-file-free (`agent-core/agent_core/domains.py:5-7`), so a YAML knob would violate
   the package's own design. The nearest existing floor,
   `GatePolicyConfig.min_calibration_n = 200` (`agent-core/agent_core/merge_gate.py:46`),
   is a gate-eligibility bar, not a fit guard.

10. **`[Certain]`/`[Likely]` evidence tags — not a convention here.** Zero occurrences
    repo-wide; review verdicts are CONFIRMED / PARTIALLY TRUE / REFUTED with file:line
    evidence (`../agents-critical-path/REVIEW.md`, lines 5-6).

11. **P0 as a "gate metric" change — PARTIALLY TRUE; must be reframed.** Redefining the
    milestone over agent records is right, but it is a *reporting* milestone: tau
    enablement is governed by `min_calibration_n=200` + `CalibratorHealth.is_trustworthy`
    (`agent-core/agent_core/merge_gate.py:39-69`) and the ADR 0005 checklist, none of
    which this plan touches. The redefinition tightens the target, which "never lower N
    silently" (`../agents-critical-path/PLAN.md`, risk register) permits — recorded via
    ADR, not a register.

## Factual drift

12. **Label counts.** 6 `timeout_clean` / 3 `ci_failure` → now 8 / 4; after `resolved()`:
    12 labeled / 19 pending / **0 audited** — so `build_domain_models` buckets are empty
    and tau is `None` in every domain, exactly as the draft's bottleneck analysis
    predicts.

13. **`experiments/` is not "~5.9K LOC", and no deletion is scheduled.** Measured: 7,444
    Python lines (4,282 non-test). Its README declares experiments short-lived *by
    policy*, but `NEXT_STEPS.md` still lists pending human steps (sign the TCB, run
    P1-P5).

14. **"Supersedes the Phase-2/3 soak-volume goals" mislocates the goals.** Soak volume is
    critical-path **Phase 3** (`../agents-critical-path/PLAN.md`, "Soak operations") plus
    `../real-data-activation/PLAN.md` step 6; Phase 2 is PR triage. `CHANGELOG.md:21`
    already records both the crossing and the ADR 0023 remediation.

15. **The elicitation guardrail is already satisfied.** "No hardcoded default that
    recreates the constant-predictor bug": the shipped proxy is config-driven and clamped
    to (0.02, 0.98) — strictly inside (0,1), never constant across changes.

16. **Two live gaps the draft missed, and one decisive lever.** (a) The acting gate
    invokes the gate with no confidence at all
    (`.github/workflows/calibrated-merge-gate.yml:52-53` — every decision at 0.0; inert
    behind `ENABLE_CALIBRATED_AUTOMERGE`). (b) The shadow job composes context with
    *neither* `--confidence` nor `--human` (:141), hitting the
    `scripts/merge_gate_context.py:135` fallback — un-prefixed agent domain at 0.0 in the
    never-synced decision log. (c) ADR 0023 (line 28) records ~18 of the 25 historical
    change_ids as Claude-authored, and those rows are still `human/*`-stamped in the live
    store: the landed F-044 backfill (`scripts/migrations/agent_domain_backfill.py`) has
    not been applied (the sole pre-07-23 agent row is PR #73's real-time self-seed, not
    backfill output). Running it is the single fastest route to the agent-record
    milestone (≈5 → ≈23 agent rows).

## Claims confirmed accurate

- The constant-predictor mathematics: PAV collapses to one block, ECE/Brier degenerate,
  AUROC 0.5 by construction — sound (and word-for-word ADR 0023 lines 19-23, the
  provenance tell).
- Only HUMAN_AUDIT feeds tau and calibrator health
  (`agent-core/agent_core/outcome_store.py:166-169`;
  `agent-core/agent_core/calibration_report.py:266` PRIMARY view) — and the human-audit
  *data* path is genuinely empty: zero `human_audit` rows in the store's entire history;
  the chain (`audit_sampler.py`, `scripts/record_audit_verdict.py`,
  `merge-gate-audit.yml`, `merge-gate-verdict.yml`) is fully implemented and has never
  been exercised.
- No fit-time degeneracy refusal exists: `_check_pairs`
  (`agent-core/agent_core/calibration.py:22-32`) is the only input validation — an
  isotonic fit on N=1 succeeds; `calibration_report.py:135-143` *detects* constant
  predictors but nothing *refuses*; and `evaluate_calibration`
  (`calibration.py:321-325`) lets a single-class slice pass the AUROC criterion.
- `_HUMAN_CONFIDENCE` is deliberate (`scripts/merge_gate_context.py:53`, ADR 0018 §5) —
  confidence stamping is a design decision, not an omission.
- The vendor-neutral sink seam does keep Braintrust-class changes cheap — at the sink
  surface only (`experiments/backend-validation/README.md:19`).
- Deferring the `experiments/` audit until after the first honest report is the right
  order.

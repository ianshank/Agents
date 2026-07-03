# Peer Review — agents Critical Path Plan (2026-07-03 draft)

**Reviewed artifact:** PLAN-2026-07-03-agents-foundation-extraction-soak (draft)
**Method:** three independent read-only verification passes against the working tree at `6cbb48b`
(merge of PR #33) and live GitHub state, plus a synthesis pass. Every falsifiable claim in the
draft was classified CONFIRMED / PARTIALLY TRUE / REFUTED with file:line evidence.
**Outcome:** the corrected plan is `PLAN.md` in this directory (v2). The draft is superseded.

## Verdict

Sound architecture, ~15 factual errors. The phase structure (scrub → extraction → triage →
clock-gated soak → redundancy pass), the no-history-rewrite decision, the fresh-import extraction,
and the soak exit gates are all correct and confirmed against the repo. However, the draft contains
errors that would cause execution failures, and two that repeat claims already refuted by an
earlier in-repo review.

## Findings that would break execution

1. **ADR 0018 is already taken.** `docs/decisions/0018-outcome-store-persistence.md` exists
   (backs F-032). The draft's two new ADRs must be numbered **0019 and 0020**. (Also noted:
   0007 is a gap in the sequence — do not backfill it.)

2. **The `e2e_acceptance` label source does not exist.** The real `LabelSource` enum
   (`agent-core/agent_core/outcome_store.py:28-32`) is `REVERT`, `CI_FAILURE`, `TIMEOUT_CLEAN`
   (passive) and `HUMAN_AUDIT` (authoritative). The invariant is "HUMAN_AUDIT always wins; tau
   and calibrator health are computed from HUMAN_AUDIT records only" — not "never pool
   e2e_acceptance with human_audit". This exact error was previously flagged in
   `docs/plans/real-data-activation/REVIEW.md:40`; the draft repeats a known-refuted claim.

3. **F-039 as a new `merge_gate_report` CLI duplicates existing code.**
   `agent_core.store_sync` already has `pull`/`push`/`stats` subcommands; `stats` emits
   per-domain / per-label-source JSON counts over `merge_outcomes.jsonl` via `store_stats()` and
   `read_store_lines()` (`store_sync.py:519-529`). A new CLI would violate the draft's own
   redundancy-hygiene standard. Corrected shape: extend `stats` with a `--soak-target` option
   and a pure `soak_progress()` function.

4. **The drift-guard step is misdirected.** `scripts/check_skill_script_drift.py` pins the
   vendored `validate_skill.py` copies inside the four domain skills to the repo-root canonical
   via SHA-256 (`TRACKED_DUPLICATES`, lines 40-47). It has no relationship to the
   `claude-foundation/` staging directory, and no workflow in `.github/workflows/` references
   the staging path. The "update drift guard config so the staging delete doesn't trip it" step
   is replaced by a verified no-op check plus a docs-link grep.

5. **The repository has no branch protection at all.** The GitHub API reports even `main` as
   `protected: false`. The draft's Phase 3 checklist item "`merge-gate-data` excluded from
   branch protection ✅" rests on a false premise, and the Phase 0 history-rewrite rationale
   must not cite branch protection. Enabling protection on `main` (with `merge-gate-data`
   excluded, or `store_sync push` breaks) is a missing endgame step, sequenced with
   "make gates required."

## Wrong standards that would have propagated into new code

6. **Logging.** The codebase uses stdlib `logging` with a plain-text format
   (`agent-core/agent_core/logging_util.py:16`, `scripts/_cli.py::configure_logging`), not
   structlog/JSON. structlog appears only inside `claude-foundation/`, whose own ADR is titled
   "stdlib-logging". The cross-cutting standard is corrected to "follow existing stdlib
   conventions."

7. **Coverage floors were conflated.** Actual enforced gates: root/`eval_harness` **96**
   (`pyproject.toml:92-97`), agent-core **95**, flow-protocol / flow-corpus /
   behavioral-regression **95**, skills **95** (all ADR 0009); `scripts/` **85**
   (F-031, `scripts/.coveragerc`); claude-foundation **85** enforced
   (`claude-foundation/pyproject.toml:54`) — the "94% branch" figure is measured, not the gate.
   F-031 is "Operational-scripts quality gates," not the repo-wide floor.

8. **Claimed enforcement that does not exist.** There is no CI grep-guard against hardcoded
   values (that was a one-time manual sweep, `docs/gap-analysis-2026-07.md:20`), and vulture is
   not configured anywhere. ruff's `F` rules (F401/F841) are already active in root and
   agent-core.

## Factual drift

9. **Rotation status.** `NEXT_STEPS.md:77` marks "Rotate Leaked Credentials" `[x]` done, yet the
   literal key pair is still present in three tracked files. The Phase 0 hard-stop is reworded:
   *confirm the checked-off rotation actually happened*; rotate immediately if unconfirmed.

10. **`eval-change-approved` label.** It exists and is applied to PRs #16, #28, and #30 — but
    **not** to activation PR #33, whose own checklist item is unchecked. Phase 3 item 1 is a
    real pending action, not ✅/❓.

11. **Foundation skill count.** `claude-foundation` ships **four** skills — `plan`,
    `code-review`, `test-first`, and `c4-docs` — not three.

12. **Gap-analysis docs.** `docs/gap-analysis-2026-07.md` (repo/scripts-wide) and
    `agent-core/GAP_ANALYSIS.md` (package-scoped) have different scopes. "Reconcile with
    cross-references," not "merge duplicates."

13. **PR #16 obsolescence is stronger than the draft states.** Its head branch
    `feat/coverage-gaps` was already merged once via PR #11 and then reused, and its
    `--cov-fail-under=96` change is already enforced on main via ADR 0009.

## Claims confirmed accurate

- Credential locations, to the line: `HARNESS_SPEC.md:309-310`, `progress.md:252` (Session 003),
  `docs/decisions/0003-langfuse-integration.md:7-8`; no other secret-shaped strings repo-wide.
- No secret scanning anywhere in active CI (`quality-gates.yml` has only `gates` +
  `eval-integrity` jobs).
- The staging tree is complete: tests, explicitly-inert CI workflow, plugin manifest v1.0.0,
  CHANGELOG, PLAN.md with M0–M6 done / M7 pending.
- ADR 0017 content as described: four domain skills stay in-repo, M7 dogfood is config+docs
  only, pinned-tag install, routing rule (generic → foundation; domain → here).
- Exactly 3 open PRs (#16 Jun 19, #21 Jun 22, #30 Jul 1) and exactly 18 remote branches, 13 of
  them merged-stale (6 `feat/agent-core-*`, 6 `claude/*`, `feat/pr-hardening-docs-snyk`).
- PR #30 correctly recovers #28, which merged into `feat/phoenix-evals`, not `main`.
- Soak state: exactly **1** record in `merge_outcomes.jsonl` on `merge-gate-data`, with
  `label: null` / `label_source: null`, seeded by PR #33's merge; N≥20 target documented in
  #33's checklist. `merge-gate-verdict.yml` is dispatch-only with an environment and auditor
  allowlist; required reviewers on the environment are genuinely unverifiable from the repo.
- F-008 is inert as claimed (`scripts/fix_loop.py:35` `FIX_ENABLED = False`, 172 LOC + tests,
  ADR 0004 human-gated).
- Registry/Protocol-DI and Pydantic `${VAR:-default}` interpolation patterns exist as described
  (`src/eval_harness/core/registry.py`, `plugins.py`, `config/__init__.py:24-46`).
- NEXT_STEPS.md drift: 150 lines, 32 `[x]` vs 6 `[ ]` items.
- Feature ledger: highest is F-036 (deferred); F-037/F-038/F-039 are free; the
  `scripts/validations/F_0XX.py` pattern holds.

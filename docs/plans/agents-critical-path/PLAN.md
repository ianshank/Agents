# Implementation Plan — ianshank/agents Critical Path (v2, post-review)

**ID:** PLAN-2026-07-03-agents-foundation-extraction-soak-v2
**Date:** 2026-07-03 · **Base commit:** `6cbb48b` (merge of PR #33)
**Supersedes:** the same-day draft; peer-review corrections in `REVIEW.md` (this directory) are
incorporated throughout.
**Scope:** Credential scrub → claude-foundation extraction (v1.0.0 + M7 dogfood) → PR triage →
merge-gate soak operations → redundancy/gap pass.
**Non-goals:** New eval-harness features before soak completion.

---

## Cross-cutting standards

| Standard | Rule | Source of truth |
|---|---|---|
| Logging | Stdlib `logging`, plain-text format — scripts via `scripts/_cli.py::configure_logging`; agent-core via `agent_core/logging_util.py` (`get_logger`, `debug_span`). No structlog/JSON in this repo. | `scripts/_cli.py`, `agent-core/agent_core/logging_util.py` |
| Coverage floors | root/`eval_harness` 96; agent-core 95; flow-corpus/flow-protocol/behavioral-regression 95; skills 95 (ADR 0009). `scripts/` 85 (F-031). claude-foundation enforced gate 85 (94 is measured, not the gate). New code states the floor of where it lands: F-039 → agent-core (95); validation scripts → scripts (85). | ADR 0009, `scripts/.coveragerc`, `claude-foundation/pyproject.toml:54` |
| Config-driven | No hardcoded tunables in new code. No CI grep-guard for this exists — enforcement is code review plus, post-extraction, `foundation_tools.scan`; gitleaks (F-037) covers secrets only. A generic hardcoded-value guard is out of scope. | — |
| Feature pattern | `features.yaml` entry + `scripts/validations/F_0XX.py` + ADR when architectural. Next IDs: F-037, F-038, F-039. Next ADRs: **0019, 0020** (0018 = outcome-store persistence, taken). | `features.yaml`, `docs/decisions/` |
| Label model | `LabelSource` = `REVERT`, `CI_FAILURE`, `TIMEOUT_CLEAN` (passive), `HUMAN_AUDIT` (authoritative). There is no `e2e_acceptance`. HUMAN_AUDIT always wins; tau/calibrator health computed from HUMAN_AUDIT only. | `agent-core/agent_core/outcome_store.py:28-32` |
| Branch protection | None exists today (`main` is unprotected). Nothing may claim exclusions as existing. Protection on `main` is a soak-endgame step; when rules are added they must exclude `merge-gate-data` or `store_sync push` breaks. | GitHub API (verified 2026-07-03) |
| Redundancy hygiene | Every phase ends with a delete list; nothing lands without removing what it replaces. | — |

**Subagent/tooling assignment (dogfoods the plugin):** `explorer` → read-only scans (Phases 0, 4);
`test-runner` → suite runs per gate; `foundation:plan` / `foundation:code-review` on every PR in
this plan; `foundation:test-first` for Phase 1 & 3 code items; `architecture-drift-guard`
(domain skill, stays in-repo per ADR 0017) post-extraction.

---

## Phase 0 — Credential scrub + secret scanning (F-037, ADR 0019; P0, ~half day)

Literal Langfuse key pair in three tracked files, while `NEXT_STEPS.md:77` marks rotation `[x]` done.

1. **Hard-stop (human):** confirm the checked-off rotation actually happened — the
   `sk-lf-e220…` / `pk-lf-ad61…` pair shows revoked in the Langfuse dashboard. If unconfirmed,
   rotate immediately. No scrub PR merges before written confirmation.
2. Scrub `HARNESS_SPEC.md:309-310`, `docs/decisions/0003-langfuse-integration.md:7-8`, and
   `progress.md` (Session 003 entry) → `<REDACTED — rotated, see incident record>`.
3. **ADR 0019 — no history rewrite** (`docs/decisions/0019-no-history-rewrite.md`). Rationale
   (must not cite branch protection — none exists): the keys are already public in remote
   history, so a rewrite removes nothing an attacker could not have taken; rotation is the real
   mitigation; a rewrite would invalidate every clone, the open-PR bases (#16/#21/#30), pinned
   SHAs, and the `merge-gate-data` branch's commit lineage.
4. **F-037 secret-scan gate:** gitleaks step in `.github/workflows/quality-gates.yml`,
   config-driven via new `.gitleaks.toml` (rules + allowlist for redaction placeholders and test
   fixtures). Fail-closed on the working tree; history scan report-only (findings are
   known/rotated per ADR 0019).
5. `scripts/validations/F_037.py` (existing `F_0XX.py` pattern): asserts `.gitleaks.toml`
   exists, the workflow wires it fail-closed, and no `sk-lf-`/`pk-lf-` literal survives in
   tracked files. `features.yaml` F-037 entry. Fix the NEXT_STEPS rotation wording.

**Exit gate:** rotation confirmed in writing; gitleaks green on main; three files clean.
**Files:** `HARNESS_SPEC.md`, `docs/decisions/0003-langfuse-integration.md`, `progress.md`,
`NEXT_STEPS.md`, `.gitleaks.toml` (new), `.github/workflows/quality-gates.yml`,
`docs/decisions/0019-no-history-rewrite.md` (new), `scripts/validations/F_037.py` (new),
`features.yaml`.

---

## Phase 1 — Extract claude-foundation + M7 dogfood (F-038, ADR 0020)

Per ADR 0017 and the staging PLAN.md (M0–M6 done). This is extraction + activation, not rewriting.

1. Create `ianshank/claude-foundation` via **fresh import** of the staging tree — no
   `git filter-repo` (consistent with ADR 0019); provenance recorded in the new repo's first
   commit message pointing at the agents SHA. Update `NEXT_STEPS.md:37-40`, which still offers
   "filter-repo or fresh import."
2. Activate the currently-inert CI workflow (verify locally first: full suite, mypy strict,
   `claude plugin validate`, headless `--plugin-dir` load). Enable branch protection in the new
   repo from day one. Tag **v1.0.0**. The foundation's enforced coverage gate is 85.
3. **ADR 0020 — extraction record** (`docs/decisions/0020-claude-foundation-extraction.md`):
   fresh-import decision, v1.0.0 pin, single-revert-point deletion.
4. **M7 dogfood in agents (config + docs only, per ADR 0017):** install the plugin pinned to
   `v1.0.0`; never vendor. Routing rule verified: the 4 domain skills (`openai-judge`,
   `architecture-drift-guard`, `eval-corpus-forge`, `model-bench`) untouched; the generic layer
   comes from the plugin (its 4 skills: `plan`, `code-review`, `test-first`, `c4-docs`; 2
   subagents; 3 hooks).
5. Delete the `claude-foundation/` staging directory in **one PR** (single revert point).
   Verified pre-condition (re-verify at execution): no workflow references `claude-foundation/`;
   `scripts/check_skill_script_drift.py` pins vendored `validate_skill.py` copies only and is
   untouched by the delete. Grep docs (NEXT_STEPS, `docs/plans/claude-foundation/`, CLAUDE.md,
   README) for staging-dir links and update them.
6. **F-038 extraction smoke:** `scripts/validations/F_038.py` — staging dir absent, pinned
   plugin config present, 4 domain skills still tracked, no generic-skill duplication.
   `features.yaml` F-038 entry.
7. Second consumer candidate: `Strategos-MCTS` — gated on its own M5 benchmark; recorded as
   follow-up only, no work here. This deletion PR satisfies the portfolio forced-migration
   criterion (first consumer removed vendored duplicates).

**Exit gate:** foundation CI green at v1.0.0; F_038 green; agents CI green with plugin installed
and staging deleted; deletion PR cleanly revertible.

---

## Phase 2 — Open-PR triage + branch pruning (~1 day)

Every legitimate merge to main writes one pending `OutcomeRecord` (seed-on-merge, F-035). The
backlog is soak fuel — but only genuine merges count.

1. **#16 (coverage hardening): close as obsolete.** Head branch `feat/coverage-gaps` was already
   merged once via PR #11 and then reused; #16's `--cov-fail-under=96` is already enforced on
   main via ADR 0009. Close citing ADR 0009; salvage only unique tests found in diff review.
2. **#21 (E2E tests, judges, Parquet/CSV): extract remainder, close.** CSV/Parquet landed as
   F-019; judge work superseded (F-028/F-030). File a tracking issue for the E2E-test remainder,
   then close #21.
3. **#30 (phoenix-live validation): review + merge.** Newest; correctly recovers #28, which
   merged into `feat/phoenix-evals`, not main. Full review with `foundation:code-review` under
   the protected-path guard; `eval-change-approved` label already applied.
4. Prune the 13 merged-stale remote branches (6 `feat/agent-core-*`, 6 `claude/*` scratch,
   `feat/pr-hardening-docs-snyk`); keep `merge-gate-data` and active PR heads. Record the delete
   list in the triage PR description.

**Exit gate:** 0 stale PRs, each closure documenting salvage decisions; branches reduced to
active work + `main` + `merge-gate-data`; soak counter incremented only by genuine merges.

---

## Phase 3 — Soak operations (human checklist + F-039)

Verified state: exactly **1** record in `merge_outcomes.jsonl` on `merge-gate-data`
(`label: null`, seeded by PR #33's merge); target **N≥20** per #33's checklist.

**Human checklist (all genuinely pending — none pre-checked):**
1. Apply `eval-change-approved` retroactively to activation **PR #33** (the label exists and is
   applied to #16/#28/#30, but not #33) or record on the PR why not.
2. `merge-gate-data` protection exclusion: moot today — no branch protection exists anywhere.
   Recorded as a hard precondition of step 5.
3. Required reviewers on the `merge-gate-verdict` environment: unverifiable from the repo —
   confirm in Settings → Environments. (`merge-gate-verdict.yml` is dispatch-only with an
   environment and auditor allowlist.)
4. Record the first verdict via the dispatch UI; establish the weekly audit cadence per ADR 0005.
5. **Endgame (clock-gated on N≥20 + ≥1 human verdict + weekly audits):** revisit the ADR 0005
   enablement checklist, then enable branch protection on `main` with the quality-gates jobs as
   required checks — the repo's first-ever protection — with `merge-gate-data` excluded from any
   rule pattern.

**F-039 — soak-stats extension (not a new CLI).** `agent_core.store_sync` already has
`pull`/`push`/`stats`; `stats` emits per-domain / per-label-source JSON via `store_stats()`.
Extend minimally:
- `agent-core/agent_core/store_sync.py`: pure function `soak_progress(records, target) -> dict`
  — total, pending vs labeled, `human_audit` count (called out separately: only HUMAN_AUDIT
  feeds tau/health), per-domain cold-start flags, N-vs-target, velocity (records/day from the
  `merged_at` span), estimated days-to-target (`None` at zero velocity). Config-driven target,
  no literals in logic.
- CLI: optional `--soak-target N` on the existing `stats` subparser; when passed, the JSON
  output gains a top-level `"soak"` key. Default behavior unchanged.
- Tests in `agent-core/tests/test_store_sync.py` (95 floor), offline fixture stores including
  malformed lines; `scripts/validations/F_039.py`; `features.yaml` entry. Property: the report
  never mutates the store.

**Exit gate:** F_039 green; `python -m agent_core.store_sync stats --soak-target 20` reports the
live soak; checklist items 1–4 human-confirmed. Gate enablement remains time-gated, not
effort-gated.

---

## Phase 4 — Redundancy & gap pass (half day, `explorer` subagent)

1. **F-008 (auto-fix loop, inert per ADR 0004):** decide schedule-or-delete — either a dated
   NEXT_STEPS entry for its enablement checklist, or a removal PR + ADR 0004 status update.
2. **Drift-guard re-check:** confirm `TRACKED_DUPLICATES` SHA pins still match the canonical
   root `validate_skill.py` (the extraction does not touch this guard).
3. **Dead code:** ruff F401/F841 are already active in root + agent-core — nothing to add there.
   Adding vulture is new work: report-only first (non-blocking CI step or make target) with an
   allowlist for intentional seams (DI protocols, plugin entry points); promote to gating only
   after a clean baseline — or skip with recorded rationale.
4. **Gap-analysis docs:** `docs/gap-analysis-2026-07.md` (repo/scripts-wide) and
   `agent-core/GAP_ANALYSIS.md` (package-scoped) have different scopes — add cross-reference
   headers in each; do not merge. Update the root doc with Phase 0–3 outcomes.
5. **NEXT_STEPS.md:** move the 32 `[x]` items into `CHANGELOG.md`; keep the 6 live items
   (≤1 screen).

**Exit gate:** F-008 decision recorded; gap docs cross-referenced; NEXT_STEPS contains only
open work; delete list executed.

---

## Sequencing

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 endgame (clock-gated) ──► "gates required"
                └────────────► Phase 4 (anytime after 1)
Phase 3 checklist items 1–4: start immediately (item 1 today); F-039 anytime after Phase 0.
```

## Risk register

| Risk | Mitigation |
|---|---|
| Rotation never happened despite `[x]` in NEXT_STEPS | Phase 0 hard-stop: written human confirmation before the scrub merges; rotate if unconfirmed |
| History-rewrite temptation | ADR 0019 — rotation is the mitigation; a rewrite breaks clones, open-PR bases, and `merge-gate-data` lineage |
| Extraction breaks agents CI | Fresh import + v1.0.0 pin; staging delete in one revertible PR; F-038 smoke |
| PR triage inflates soak with junk merges | Regression gate + `foundation:code-review` on every triage merge; closures don't count |
| Soak stalls (low merge velocity, 1 record today) | F-039 velocity/days-to-target surfaces it weekly; fallback: stay in shadow mode, adjust per-domain expectations only via a new ADR — never lower N silently |
| Adding branch protection breaks store-sync | Endgame rule explicitly excludes `merge-gate-data` |
| Gold-plating | Each phase's code budget is fixed; anything beyond requires a new feature entry with justification |

## Acceptance summary

- F-037 gitleaks gate green; rotation confirmed; zero key strings in the working tree
- claude-foundation v1.0.0 tagged; agents consuming via pinned install; staging deleted
  (forced-migration criterion met)
- #16/#21 closed with salvage notes; #30 merged; 13 stale branches pruned
- Soak observable via `store_sync stats --soak-target` (F-039); human checklist items 1–4 done;
  first human verdict recorded
- ADRs 0019/0020 accepted; F-008 decided; gap docs cross-referenced; NEXT_STEPS ≤1 screen

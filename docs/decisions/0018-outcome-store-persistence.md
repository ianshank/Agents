# 0018 — Merge-gate outcome-store persistence: dedicated data branch

- Status: **Accepted.**
- Date: 2026-07-03
- Related: ADR 0005 (calibrated merge gate), `docs/plans/real-data-activation/PLAN.md` +
  `REVIEW.md`, F-032 (store sync), F-033 (scheduled labeller), F-034 (audit surface),
  F-035 (shadow gate + seed-on-merge).

## Context

The calibrated merge gate (ADR 0005) is a pure, tested subsystem starved of data: its
outcome store (`merge_outcomes.jsonl`) lives in the ephemeral CI runner workspace, and no
workflow commits, caches, or restores it. Records seeded in run N are gone in run N+1, so
labels can never accumulate and every domain stays in cold-start ESCALATE forever. Closing
that seam requires choosing where the store persists, who may write it, what real merges
seed into it, and how concurrent writers are reconciled.

## Decision

### 1. Backend: an orphan data branch `merge-gate-data`

The store persists as the single root-level file `merge_outcomes.jsonl` on a dedicated
branch `merge-gate-data`. The branch is bootstrapped lazily: the first
`agent_core.store_sync push` creates a **parentless root commit** when the remote ref does
not exist — no manual branch creation, and the branch is never pushed from a developer
machine. Rejected alternatives:

- **Actions cache / artifacts**: caches are best-effort and artifacts expire; both violate
  "labels accumulate over wall-clock time".
- **External storage (S3 or similar)**: a new credential surface, against the repo's
  local-first posture.

The branch is diffable and auditable — commit authorship attributes every write, including
human verdicts.

### 2. Credentials: the default `GITHUB_TOKEN`, job-scoped

Writer workflows use the default `GITHUB_TOKEN` with job-scoped
`permissions: contents: write`. No PAT, no new secret. `pull_request`-triggered jobs sync
**read-only** (fetch/merge, never push): fork PRs carry a read-only token, and a PR-time
job has nothing legitimate to persist. Seeding therefore happens on `push` to `main`
(see 5), never on a `pull_request` event. The data branch must be excluded from branch
protection (human checklist item).

### 3. Concurrency: the retry loop is the mechanism; no shared concurrency group

Cross-workflow serialization via a shared `concurrency:` group was considered and
**rejected**: GitHub keeps at most one pending run per group and *replaces* the queued
run, so bursty merges would silently cancel a queued seed run — and a cancelled seed is an
unrecoverable data loss (nothing re-seeds a merged change). Correctness comes solely from
`store_sync`'s fetch → re-merge → push retry loop, which is designed for concurrent
writers: a rejected push means a competitor won; the writer refetches, re-merges (its
records survive the union), and retries with exponential backoff.

### 4. Canonical deterministic record ordering

`OutcomeStore.resolved()` picks the winning passive label by **file position**. The merged
store is therefore always written in a canonical order — sorted by
`(merged_at, labeled_at is not None, labeled_at, label_source, change_id)` — so any
interleaving of the same record sets yields a byte-identical store and an identical
`resolved()` view on every runner. Deduplication is by the **full canonical record JSON**
(`OutcomeRecord.to_json()`, `sort_keys=True`): only byte-identical duplicates are dropped;
the union never discards a `HUMAN_AUDIT` line. `HUMAN_AUDIT`-wins precedence remains
`resolved()`'s job, not sync's.

Assumption recorded: **at most one passive label per change**. `resolved()`'s positional
tie-break would let a later `timeout_clean` (correct) shadow an earlier `revert`
(incorrect). The single, daily, sequential labeller preserves the assumption — do not add
a second passive-label writer without revisiting this.

### 5. Seed-input conventions (consumed by F-035)

- `change_id` = the commit SHA that landed on `main` (`GITHUB_SHA` of the push event) —
  the merge commit of record, compatible with revert detection's SHA-prefix matching.
  Known limitation: a rebase-merge of N commits seeds only the head SHA — one record per
  integrated change-set.
- `domain` = first-match-wins lookup over the changed files in the committed
  `config/merge-gate-domains.yaml`; unmapped files fall to its `default_domain`.
- **All merges currently seed under the reserved `human/<domain>` namespace with
  `raw_confidence = 0.0`.** No author/branch heuristic is used, because none recovers a
  real confidence value, and a guessed confidence pooled into an agent domain is the
  calibration-poisoning path documented in `REVIEW.md` §6: `BinningCalibrator.predict()`
  returns a bin's *empirical accuracy*, so mostly-correct human outcomes at 0.0 would let
  genuinely low-confidence agent changes inherit p≈1.0. The mapping never emits `human/`
  domains, so per-domain isolation in `build_domain_models` keeps every human outcome out
  of every agent calibrator with zero TCB change. Agent-reported confidence enters later
  via an explicit confidence-artifact convention (F-036 territory; the
  `merge_gate_context.py --confidence` flag is the seam).

Consequence, recorded deliberately: **the agent-domain soak is plumbing-only.** Until an
agent-confidence artifact exists, every shadow decision on an agent domain is cold-start
ESCALATE. The shadow job therefore also logs a second, log-only decision against
`human/<domain>` — the domains that actually accumulate audits — so the calibrator /
`tau` / health path is exercised end-to-end without touching any acting path.

### 6. Commit hygiene

Data-branch commits are produced with git plumbing (`hash-object` → `mktree` →
`commit-tree`) so the checked-out worktree and index are never touched, with an explicit
`-c user.name/-c user.email` ident (runners have none). Messages follow
`store-sync: <n> records [skip ci]` plus an `Actor: <github.actor>` trailer for
human-triggered writes; `[skip ci]` keeps data pushes from triggering workflows.

Implementation obligation (from adversarial review): `store_sync` must gate on the fetch
return code **before** reading `FETCH_HEAD` — `actions/checkout` leaves a stale
`FETCH_HEAD` behind, and an unguarded read would silently use the wrong commit. An absent
remote branch ("couldn't find remote ref") is cold start, not an error; any other fetch
failure aborts the sync with the store untouched.

## Consequences

- Records survive between CI runs; labels can accumulate; the F-033 labeller and F-034
  audit surface have a durable substrate.
- Store writes are auditable via data-branch history; human verdicts are attributed by
  actor trailer and commit authorship.
- The store grows unbounded on one branch; compaction (rewriting resolved history) is
  deliberately out of scope — append-only is the tamper-evidence property.
- Human checklist: exclude `merge-gate-data` from branch protection; enable required
  reviewers on the `merge-gate-verdict` environment (ADR 0005's CODEOWNERS-grade verdict
  requirement).

# PLAN — Real-Data Activation (F-032 … F-036), v2

> Spec-driven execution plan for Claude Code. Scope: make real outcome data flow
> through the already-built calibrated-gate machinery in this repository.
> **This plan adds almost no new mechanism.** Any drift toward new metrics,
> new gates, new label sources, or new abstractions is out of scope and must be
> rejected.
>
> v2 supersedes the v1 draft after peer review — see [`REVIEW.md`](REVIEW.md)
> for the findings this version incorporates. Structure, scope, and non-goals
> are unchanged; the ground-truth section, label taxonomy, CLI invocations, and
> four under-specified seams (shadow input wiring, seed inputs, labeller
> preconditions, verdict-dispatch idempotency) are corrected.

---

## 0. Ground Truth (verified against the codebase, 2026-07-03)

- `agent_core` gate machinery exists and is green: `merge_gate`,
  `outcome_store`, `outcome_labeller`, `audit_sampler`, `detectors`,
  `merge_seed`, `merge_gate_ci` (all under `agent-core/agent_core/`), covered
  by `agent-core/tests/` at the package's 95% coverage floor.
- `.github/workflows/calibrated-merge-gate.yml` is inert (job-level `if` on the
  repo variable `vars.ENABLE_CALIBRATED_AUTOMERGE`, unset) and points `STORE`
  at `merge_outcomes.jsonl` — **a file in the ephemeral runner workspace with
  no persistence mechanism between CI runs**. No workflow commits, caches, or
  restores it. Records seeded in run N are gone in run N+1. This is the seam
  ADR 0005 left open ("a populated store" is a precondition it never wires),
  and it starves everything downstream.
- Store writers: the CLIs `merge_seed`, `outcome_labeller`,
  `audit_sampler record`, plus the default-off `merge_gate_ci --seed-store`
  seam (seeds on AUTO_MERGE only; the workflow does not pass it). Nothing runs
  on a schedule.
- `LabelSource` is exactly `REVERT`, `CI_FAILURE`, `TIMEOUT_CLEAN` (passive)
  and `HUMAN_AUDIT` (authoritative) — `outcome_store.py:28-32`. There is no
  other label source; this plan introduces none.
- Zero `HUMAN_AUDIT` labels exist anywhere (no committed store, no data
  branch). Every domain is in permanent cold-start ESCALATE.
- `flow_corpus` is fully synthetic (`MockPolicy`); correctly firewalled via the
  `"corpus_oracle"` label-source string (`flow_corpus/validation/runner.py:37`)
  which calibration ignores (it filters on `HUMAN_AUDIT` only).
- `merge_gate_ci` defaults are fail-safe but shadow-hostile: `mech_pass`
  defaults `False` → an unwired invocation REJECTs (exit 20), and the current
  workflow treats exit 20 as job failure. Shadow mode must wire inputs and
  remap exits (F-035).
- No E2E sandbox harness exists in this repo — not as code and not as a spec.
  Anything of that shape is net-new and explicitly out of scope here.

## 1. Objective and Definition of Done

**Objective:** the first shadow-mode gate decision on a real PR, computed from
a persistent store containing real seeded records, machine labels, and ≥1
human audit verdict recorded through the new audit surface.

**Definition of Done (plan level):**
1. A PR merged after this plan lands produces a pending `OutcomeRecord` that is
   still present in the store one week later. (F-032 + seeding enabled)
2. The scheduled labeller resolves that record with a **passive** label source
   (`revert`, `ci_failure`, or `timeout_clean`) without human action. (F-033)
3. The audit sampler opens a review task for a sampled record and a human
   verdict lands in the store as `HUMAN_AUDIT` via the documented path. (F-034)
4. Every subsequent PR carries a shadow gate decision (log-only) in its checks.
   (F-035)

## 2. Invariants (Claude Code MUST NOT violate)

These restate ADR 0005 / repo invariants. Violations fail review regardless of
tests passing.

- **I-1 Label separation:** passive labels (`revert`, `ci_failure`,
  `timeout_clean`) are monitoring signals only and are never pooled with
  `HUMAN_AUDIT` for calibration — `build_domain_models` filters on
  `HUMAN_AUDIT` and this plan must not weaken that filter. No automated path
  writes `LabelSource.HUMAN_AUDIT` except the human-triggered verdict dispatch
  (F-034). `corpus_oracle` records never enter the merge-gate store. **No new
  label source is introduced.**
- **I-2 TCB carve-out:** `agent_core/calibration.py`, `merge_gate.py`,
  `outcome_store.py` semantics, and `audit_sampler.py` sampling/verdict logic
  are protected paths. Prefer zero changes; anything unavoidable is
  additive-only with explicit human review. Idempotency, dedupe, and
  precondition guards live in the new wrapper/workflow layer, not the TCB.
- **I-3 Fail-safe:** every new automated path fails toward ESCALATE / no-op /
  abort-before-write, never toward AUTO_MERGE or toward optimistic labels.
  Auto-merge enablement stays a human checklist item (ADR 0005) and is a
  non-goal here.
- **I-4 No hardcoded values:** tunables via frozen config dataclasses and CLI
  flags, matching `agent_core.config` patterns. `agent_core` reads no
  environment variables; workflows map repo variables onto CLI flags. The
  path→domain mapping (F-035) is a committed config file, not inline YAML.
- **I-5 Backwards compatibility:** store schema changes are avoided; if one
  ever becomes necessary it follows the existing optional-field back-compat
  pattern (`OutcomeRecord.agent_version`, `outcome_store.py:44-47`) so
  pre-existing JSONL lines still load.
- **I-6 Spec conventions:** each feature gets a `features.yaml` entry
  (continue at F-032; `deferred` status per the F-008 precedent), a
  `scripts/validations/F_0XX.py` guard (deterministic/offline where possible,
  like `F_031.py`), tests at the owning package's coverage floor (agent-core:
  95%), and an ADR in `docs/decisions/` where a decision is made (next: 0018).

## 3. Features

### F-032 — Outcome-store persistence seam  *(the only substantial new code)*

**Problem:** `calibrated-merge-gate.yml` reads/writes `merge_outcomes.jsonl` in
an ephemeral runner workspace. Seeded records cannot survive between runs, so
labels can never accumulate. Everything downstream is starved by this gap.

**Decision required (write ADR 0018 in `docs/decisions/`):** choose ONE
persistence backend:
- **(a) Dedicated data branch** (`merge-gate-data`): workflows fetch the
  branch, merge-append, commit with `[skip ci]`, push. Pros: diffable,
  auditable (commit authorship attributes every write, including human
  verdicts), zero external deps. Cons: push races under concurrency —
  mitigated by `store_sync`'s fetch→rebase→push retry loop, which is the
  module's core correctness obligation (the existing per-ref `concurrency:`
  group does not serialize across the four writer workflows).
- (b) GitHub Actions cache/artifact: rejected — artifacts expire and caches are
  best-effort; both violate "labels accumulate over wall-clock time."
- (c) External storage (S3): rejected for now — new credential surface, against
  local-first posture.

Recommendation: **(a)**, implemented as a small `agent_core.store_sync` module
(pull → merge-append → push; append-only union keyed by
`(change_id, label_source, labeled_at)`; conflict semantics defer to the
existing `HUMAN_AUDIT`-wins resolution in `outcome_store.resolved()` — sync
never drops a `HUMAN_AUDIT` line). Because `resolved()`'s passive-label
resolution is **file-order dependent** ("latest labeled wins" by position,
`outcome_store.py:85-86`), the merged store must be written in a canonical
deterministic order — a stable sort keyed by
`(merged_at, has_label, labeled_at, label_source, change_id)`, where the
`has_label` component orders pending records before labeled ones — so any
interleaving of the same
record sets yields a byte-identical store and an identical `resolved()` view
on every runner. ADR 0018 additionally fixes two conventions the features
below depend on:
- **Credentials:** the default `GITHUB_TOKEN` with job-scoped
  `permissions: contents: write` (data branch stays outside branch
  protection). No fine-grained PAT, no new secret surface.
  `pull_request`-triggered jobs sync **read-only** (fetch/merge, never push).
- **Seed-input conventions** (consumed by F-035): `change_id` = merge-commit
  SHA; `domain` = lookup in the committed path→domain mapping (default domain
  for unmapped paths); `raw_confidence` = agent-reported value for
  agent-authored changes. **Human-authored changes carry no agent confidence
  and must never enter an agent domain's calibration**: a naive `0.0` sentinel
  pooled into the agent's domain would be a poisoning path, because
  `BinningCalibrator.predict()` returns the bin's *empirical accuracy* — a
  bottom bin filled with mostly-correct human outcomes approaches 1.0, so a
  genuinely low-confidence agent change (e.g. 0.05) would inherit p≈1.0,
  potentially clear `tau`, and satisfy the Wilson bin floor on the strength of
  human outcomes (violating I-3). Convention: human-authored changes are
  seeded with `raw_confidence=0.0` under a **reserved domain namespace**
  (`human/<mapped-domain>`) that the path→domain mapping never emits for gate
  lookups. Per-domain model isolation (`build_domain_models` groups by
  `domain`) then guarantees these records — and any `HUMAN_AUDIT` verdicts on
  them — can never feed an agent domain's calibrator, `tau`, or bin
  statistics, with **zero TCB changes** (I-2), while still exercising
  persistence, labeller, and audit machinery end-to-end. Agent domains leave
  cold start only on real agent-authored records, which is the honest
  behaviour.

**Acceptance criteria:**
- AC-1: A record appended in workflow run N is readable in run N+1 (integration
  test using a temp bare git repo as the remote; no live GitHub in tests, per
  invariant "external calls mocked").
- AC-2: Two concurrent appends both survive (retry-rebase path tested with
  interleaved pushes to the temp bare remote).
- AC-3: `HUMAN_AUDIT` records are never dropped or overwritten by sync
  (property test).
- AC-4: `scripts/validations/F_032.py` guards that every workflow referencing
  the store also invokes `store_sync`, and that no `pull_request`-triggered
  job invokes the push path.
- AC-5: Deterministic merge order: syncing the same record sets in any
  interleaving yields a byte-identical store file, and
  `OutcomeStore.resolved()` returns the same authoritative record per
  `change_id` regardless of sync order (property test; `resolved()`'s
  passive-label resolution is file-order dependent, so canonical ordering is
  a correctness requirement, not cosmetics).

### F-033 — Scheduled labeller workflow

**Problem:** `outcome_labeller` + `detectors` exist but nothing invokes them.

**Work:** new `.github/workflows/outcome-labeller.yml` on `schedule:` (daily —
within ADR 0005's "fixed schedule (e.g. weekly)" cadence; the
`maturity_days=7` window still gates `TIMEOUT_CLEAN`) + `workflow_dispatch`.
Steps: sync store (F-032, read) → precondition guard → run
`python -m agent_core.outcome_labeller --store <path> --repo-dir . --repo <owner/name>`
over pending records → sync back (write). No new Python in `agent_core`.

The precondition guard exists because the detectors fail *safe toward no
signal*, and in the labeller "no signal + matured" becomes
`TIMEOUT_CLEAN = correct`: a shallow checkout (revert footers invisible) or a
missing `gh` token (check-runs invisible) would silently produce
systematically optimistic labels. The workflow checks out with
`fetch-depth: 0`, provides an authenticated `gh`, and aborts before any store
write-back if either substrate is unavailable.

**Acceptance criteria:**
- AC-1: Given a seeded pending record and a repo fixture containing a
  revert-footer commit, one labeller invocation resolves the record to
  `label=false`, `label_source="revert"` (existing detector tests extended to
  the workflow entry path).
- AC-2: Idempotent: a second run over the same store appends nothing (the
  labeller skips records whose resolved view is already labelled).
- AC-3: The labeller never emits `HUMAN_AUDIT` (structural test; also I-1).
- AC-4: Workflow failure — including a failed precondition guard — leaves the
  remote store untouched (write-back sync is the last step; I-3).
- AC-5: `F_033.py` guards the workflow config: `fetch-depth: 0`, token wiring,
  and guard-before-write-back ordering.

### F-034 — Audit queue surface (human-in-the-loop)

**Problem:** `audit_sampler` can select records and record verdicts, but no
surface puts sampled records in front of a human, so zero `HUMAN_AUDIT` labels
exist.

**Work:** scheduled workflow (weekly, per ADR 0005's cadence section) that:
1. Syncs store, runs `python -m agent_core.audit_sampler --store <path> select`.
2. Opens/updates one GitHub issue per sampled `change_id`, labeled
   `merge-gate-audit`, body containing the record context and the exact
   verdict commands:
   `python -m agent_core.audit_sampler --store <path> record --change-id <id> --correct`
   (or `--incorrect`).
3. A companion `workflow_dispatch` job (`inputs: change_id, verdict`) executes
   that command with store sync, so the human never touches JSONL by hand.
   The dispatch path is the **only** automated writer of `HUMAN_AUDIT`, and it
   is human-triggered by construction. Before invoking the sampler, the
   dispatch wrapper checks the resolved view: if the `change_id` already
   carries a `HUMAN_AUDIT` label it exits as a logged no-op (the TCB's
   `record_verdict` appends unconditionally; the wrapper — not the sampler —
   provides idempotency, per I-2). The triggering `github.actor` is recorded
   in the data-branch commit message and the workflow run log, satisfying ADR
   0005's "verdicts come from a human" attribution without touching the
   `OutcomeRecord` schema.

Note: `select_for_audit` is random and non-persistent per run, and
`per_domain_floor=30` selects nearly everything in the early low-volume
regime — AC-2's dedupe is load-bearing, not cosmetic.

**Acceptance criteria:**
- AC-1: Sampler selection and verdict logic untouched (I-2); only the surface
  is new.
- AC-2: Duplicate issues are not created for a `change_id` that already has an
  open (or closed-as-audited) `merge-gate-audit` issue.
- AC-3: Verdict dispatch writes exactly one `HUMAN_AUDIT` record and closes the
  issue; re-dispatch on an already-audited record is a logged no-op enforced
  by the wrapper pre-check.
- AC-4: `F_034.py` guards that no `schedule:`-triggered job can reach the
  verdict-writing code path (dispatch-only), and that the dispatch job records
  the actor.

### F-035 — Shadow-mode gate on every PR

**Problem:** the gate has never produced a decision on a real PR; enabling
auto-merge without a soak period would be untested in exactly the dimension
that matters.

**Work:** modify `calibrated-merge-gate.yml` (or add `merge-gate-shadow.yml`)
to run on every PR **unconditionally in log-only mode**, plus seed-on-merge.

*Input wiring (new subsection — without it the shadow gate REJECTs every PR,
because `mech_pass` defaults `False` and mechanical failure is unconditional
REJECT):*
- `mech_pass` ← the regression-gate result (same-workflow `needs:` / step
  outcome; the existing `quality-gates.yml` machinery is the source of truth).
- `touches_protected` ← the existing protected-path classification
  (`scripts/check_protected_changes.py` / `scripts/eval_protected_paths.py`,
  already named as the upstream feed in `merge_gate_ci.py`'s docstring).
- `domain` ← committed path→domain mapping config (I-4); unmapped → default
  domain. The mapping never emits `human/`-prefixed domains (those are
  reserved for seeding human-authored changes, ADR 0018).
- `raw_confidence` ← agent-reported value when present; human-authored
  changes seed at `0.0` under the reserved `human/<domain>` namespace so they
  never enter agent-domain calibration (ADR 0018 seed-input conventions).

*Shadow exit-code contract:* all three decision codes (0 AUTO_MERGE /
10 ESCALATE / 20 REJECT) map to job **success**; only 1 (internal error) and
2 (usage error) fail the job. A shadow that can fail a check is not shadow.
The decision is surfaced via `$GITHUB_STEP_SUMMARY` (no extra permissions)
rather than a sticky PR comment. Store sync in this job is read-only (I-3,
fork safety). `ENABLE_CALIBRATED_AUTOMERGE` continues to gate only the
*acting* path (today a stub step).

*Seed-on-merge:* enable the existing `merge_seed` CLI on merge events
(`pull_request: closed` + `merged == true`, or push-to-main): every real merge
writes one pending record via F-032 sync, using the ADR 0018 seed-input
conventions.

**Acceptance criteria:**
- AC-1: Shadow job cannot merge, approve, or block: `permissions:` restricted
  (contents: read only), decision exit codes 0/10/20 all succeed, and both
  properties asserted by `F_035.py` (workflow-lint style, like `F_031.py`).
- AC-2: The step-summary decision includes domain, decision, reason string
  (`p/tau/health/n/ece/auroc/bin` as emitted by `merge_gate_ci`), and store
  record counts per label source (observability for the soak).
- AC-3: Seed-on-merge writes exactly one pending record per merged PR keyed by
  merge-commit SHA (idempotency already in `merge_seed`; test the workflow
  wiring against a temp bare remote).
- AC-4: With an empty store the shadow decision is ESCALATE and the job
  succeeds (cold-start is not an error).
- AC-5: A REJECT decision (e.g. `mech_pass=false`) is reported in the summary
  and the shadow job still succeeds.

### F-036 — Real-transcript corpus bridge  *(DEFERRED — do not implement)*

Placeholder only: an ingestion path from labeled store records into a
`flow_corpus` suite, replacing `MockPolicy` for validation of the live system.
Blocked until F-032…F-035 have soaked and ≥1 domain has non-trivial audit
history. Record as `status: deferred` in `features.yaml` (F-008 precedent) so
the intent is tracked without inviting premature mechanism.

## 4. Explicit Non-Goals

- E2E sandbox harness / container isolation (does not exist in this repo, even
  as a spec; stays out of scope).
- Enabling auto-merge (`ENABLE_CALIBRATED_AUTOMERGE`) — human checklist,
  ADR 0005, outside Claude Code's authority.
- New calibration math, new metrics, new gate policies, new label sources,
  multi-agent trust.
- Any edit to TCB semantics (I-2).
- `claude-foundation` extraction — separate repo operation, human-driven,
  tracked in NEXT_STEPS.md; not part of this plan.

## 5. Execution Order & Checkpoints

| Step | Feature | Owner | Gate to proceed |
|---|---|---|---|
| 1 | ADR 0018 (persistence + seed-input + token conventions) | Claude Code drafts, **human approves** | ADR merged |
| 2 | F-032 store_sync + tests + validation | Claude Code | CI green, human review (touches store I/O boundary) |
| 3 | F-033 labeller workflow | Claude Code | CI green |
| 4 | F-035 shadow gate + input wiring + seed-on-merge | Claude Code | First real PR shows shadow decision + persisted seed |
| 5 | F-034 audit surface | Claude Code | **Human records first verdict** |
| 6 | Soak: N≥20 shadow decisions, weekly audits | Human | Only then revisit ADR 0005 enablement checklist |

Each step lands as its own PR with `features.yaml` entry, `F_0XX.py`
validation, tests, and a one-paragraph NEXT_STEPS.md delta (do not add
changelog prose there — CHANGELOG.md exists for that).

## 6. Prompting Contract for Claude Code Sessions

Paste per session:

> Implement F-0XX from docs/plans/real-data-activation/PLAN.md exactly.
> Invariants I-1…I-6 are hard constraints; if the task appears to require
> touching `agent_core/{calibration,merge_gate,outcome_store,audit_sampler}.py`
> semantics, STOP and report instead of proceeding. The only label sources are
> REVERT / CI_FAILURE / TIMEOUT_CLEAN / HUMAN_AUDIT — introduce no new ones.
> Acceptance criteria are the definition of done; do not add features, metrics,
> or abstractions beyond them. All external calls mocked in tests; agent-core
> coverage floor 95%; Protocol DI; no hardcoded values; JSON logging via
> `agent_core.logging_util`.

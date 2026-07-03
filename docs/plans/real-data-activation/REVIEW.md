# Peer Review — "PLAN — Real-Data Activation (F-032 … F-036)" (draft v1)

- Reviewed: 2026-07-03, against branch `claude/real-data-activation-plan-7y1ba8`
  (HEAD `3cca8ae`, identical to `main` at review time).
- Method: every claim in the draft's "Ground Truth" section and every acceptance
  criterion was checked against the source tree. All citations below are
  `file:line` in this repository.
- Companion document: [`PLAN.md`](PLAN.md) is the corrected v2 plan that
  incorporates every finding here.

## Verdict

**The architecture is sound and the core defect diagnosis is correct. The plan
is approvable only after correction:** its "verified" ground-truth section
contains factual errors (a label source and a spec that do not exist, a wrong
CLI verb, a misattributed schema-version discipline), and it under-specifies
four seams that would break F-033/F-034/F-035 exactly as drafted — most
seriously, an unwired shadow gate would fail every PR with REJECT rather than
observe it.

None of the findings invalidate the plan's scope discipline ("adds almost no
new mechanism") — in fact, correcting the label-taxonomy error *shrinks* the
plan, because no new `LabelSource` is needed at all.

## 1. Ground-truth claims, verified

| # | Draft claim | Verdict | Evidence |
|---|---|---|---|
| 1 | Gate machinery (`merge_gate`, `outcome_store`, `outcome_labeller`, `audit_sampler`, `detectors`, `merge_seed`, `merge_gate_ci`) exists | **TRUE** | all eight modules under `agent-core/agent_core/` |
| 2 | "343 passed, 2 xfailed" | **UNVERIFIED** | agent-core has 311 `def test_` functions and exactly one `xfail` marker (`agent-core/tests/test_sanitize.py:92`, `strict=False`); the number matches no directory's raw count. Not load-bearing, but a plan that opens with "verified against the codebase" must not include numbers that cannot be reproduced |
| 3 | `calibrated-merge-gate.yml` is inert; `ENABLE_CALIBRATED_AUTOMERGE` unset | **TRUE (nuance)** | job-level `if` on the **repo variable** `vars.ENABLE_CALIBRATED_AUTOMERGE` (`.github/workflows/calibrated-merge-gate.yml:27`), not an env var |
| 4 | Store file has **no persistence between CI runs** | **TRUE — the load-bearing finding** | `STORE: ${{ vars.MERGE_GATE_STORE \|\| 'merge_outcomes.jsonl' }}` (`calibrated-merge-gate.yml:48`) lives in the ephemeral runner workspace; no workflow commits, caches, or uploads it (only artifact anywhere is `regression_report.json`, `quality-gates.yml:83`) |
| 5 | Only writers are manual CLIs | **PARTIALLY TRUE** | `merge_seed`, `outcome_labeller`, `audit_sampler record` — plus one default-off automated writer the draft misses: `merge_gate_ci --seed-store` seeds on AUTO_MERGE (`agent-core/agent_core/merge_gate_ci.py:134-142`; the workflow does not pass the flag) |
| 6 | Zero `HUMAN_AUDIT` labels exist; permanent cold-start ESCALATE | **TRUE** | no committed store file, no `merge-gate-data` branch, `HUMAN_AUDIT` appears only in code/tests |
| 7 | `flow_corpus` synthetic via `MockPolicy`; firewalled via `corpus_oracle` | **TRUE** | `flow-corpus/flow_corpus/policy/mock.py:24`; `_ORACLE_LABEL_SOURCE = "corpus_oracle"` with the firewall rationale (`flow-corpus/flow_corpus/validation/runner.py:33-37`), asserted by `flow-corpus/tests/test_validation.py:66`. Note: it is a distinct source *string*, not a `LabelSource` member — the exclusion happens because calibration filters on `HUMAN_AUDIT` only (`agent-core/agent_core/outcome_store.py:163`) |
| 8 | E2E sandbox harness (TaskSpec/AgentRunner/SandboxExecutor/OutcomeScorer) is "spec-only; 0% implemented" | **FALSE** | zero grep hits for any of the four identifiers in code, specs, or docs. It is not spec-only; it is **nonexistent under those names**. Harmless (the plan defers it), but "ground truth" must not cite artifacts that aren't there |

## 2. Factual errors that must be corrected (fixed in PLAN.md v2)

1. **`e2e_acceptance` does not exist.** The real `LabelSource` enum is `REVERT`,
   `CI_FAILURE`, `TIMEOUT_CLEAN`, `HUMAN_AUDIT`
   (`agent-core/agent_core/outcome_store.py:28-32`). The draft's Definition of
   Done #2, F-033 AC-1, and invariant I-1 are all stated in terms of a label
   source that no code emits or recognizes. Corrected framing: the labeller
   resolves records with a **passive** source (`revert` / `ci_failure` /
   `timeout_clean`); the invariant is "never pool passive labels with
   `HUMAN_AUDIT`" — which is exactly what `build_domain_models` already
   enforces. **This correction removes work**: no enum change, which also keeps
   the protected `outcome_store.py` untouched (I-2).
2. **Wrong CLI verb in the human-facing command.** The audit subcommand is
   `record`, not `record-verdict`, and `--store` is a global argument that
   precedes the subcommand
   (`agent-core/agent_core/audit_sampler.py:81-104`). The command the draft
   would print into every audit issue —
   `python -m agent_core.audit_sampler record-verdict --store … --correct true` —
   fails on argparse twice over (`record-verdict` is not a subcommand;
   `--correct`/`--incorrect` are store_true/store_false flags, not
   `true|false` values). Correct form:
   `python -m agent_core.audit_sampler --store <path> record --change-id <id> --correct`
   (or `--incorrect`).
3. **No `SCHEMA_VERSION` in `outcome_store.py`.** The only `SCHEMA_VERSION`
   (`1.3.0`, `agent-core/agent_core/version.py:17`) versions the *config*
   schema. The store's actual compatibility discipline is optional-field
   back-compat on `OutcomeRecord` (the `agent_version` pattern,
   `outcome_store.py:44-47`). Invariant I-5 is restated accordingly.
4. **Repo-convention slips.** ADRs live in `docs/decisions/` (not `docs/adr/`;
   a `docs/adr/` exists only nested inside `claude-foundation/`). ADR
   numbering: 0017 is the max, so 0018 is correct (0007 is a gap in the
   sequence). Coverage floors are not a flat 95%: agent-core / flow-corpus /
   flow-protocol / behavioral-regression = 95, root `eval_harness` = 96,
   `scripts/` and `claude-foundation` = 85. Invariant I-4's "config objects /
   env" is half-wrong: `agent_core` reads **no environment variables** (no
   `os.environ`/`getenv` in the package); tunables are config dataclasses +
   CLI flags, and workflows map repo variables onto flags.

## 3. Design gaps (the substantive findings; fixed in PLAN.md v2)

### A. The shadow gate, as drafted, fails every PR with REJECT

`merge_gate_ci` defaults `mech_pass=False`
(`agent-core/agent_core/merge_gate_ci.py:125`) and `decide()` treats a
mechanical failure as unconditional REJECT (ADR 0005 §Decision 1). The current
workflow passes neither `--mech-pass` nor a context file
(`calibrated-merge-gate.yml:52`), so a shadow run wired the same way returns
exit 20 on every PR — and the existing exit-code mapping fails the job on 20.
The draft's F-035 says "run merge_gate_ci → post the decision" without wiring
inputs, and its ACs only cover the empty-store/ESCALATE case (AC-4), not
REJECT. Two required fixes:

1. **Wire the real inputs**: `mech_pass` from the regression-gate result
   (same-workflow `needs:`/step outcome), `touches_protected` from the
   existing protected-path scripts (`scripts/check_protected_changes.py`,
   `scripts/eval_protected_paths.py` — already named as the upstream feed in
   `merge_gate_ci.py:5-9`), `domain` from a committed path→domain mapping
   config (I-4), `raw_confidence` per the seeding convention (gap B).
2. **Shadow exit-code contract**: all three *decision* codes (0/10/20) map to
   job success; only 1 (internal) and 2 (usage) may fail the job. A shadow
   that can fail a check is not shadow.

### B. Seed-on-merge inputs are undefined

`merge_seed` requires `--change-id --domain --raw-confidence`
(`agent-core/agent_core/merge_seed.py:87-125`). For a real, human-authored
merged PR there is no agent-reported confidence, and the workflow's domain
default is `'unknown'`. The draft never says what values to seed. ADR 0018
must fix the conventions (v2 proposes: change_id = merge-commit SHA; domain
from the same mapping as gap A; `raw_confidence` = explicit
`0.0` sentinel for non-agent changes, with the calibration implication written
down: HUMAN_AUDIT-labeled records at confidence 0.0 populate only the bottom
calibrator bin and can never raise `tau` into auto-merge territory — the
fail-safe direction).

### C. Optimistic-label hazard in the scheduled labeller

The detectors "fail safe" by degrading to *no signal* when git history or
`gh` is unavailable (`agent-core/agent_core/outcome_labeller.py:99-103`,
`detectors.py`). But in the labeller, "no signal + matured" **is** a label:
`TIMEOUT_CLEAN = correct` (`outcome_labeller.py:70-71`). A scheduled workflow
with a shallow checkout (revert footers invisible) or a missing GH token
(check-runs invisible) therefore yields systematically optimistic labels and
looks green while doing so. ADR 0005 already flags TIMEOUT_CLEAN as biased
optimistic; the workflow must not widen that bias. F-033 v2 adds ACs:
`fetch-depth: 0`, an authenticated `gh`, and a precondition guard that aborts
the run (before any store write-back) when either detector's substrate is
absent.

### D. Verdict re-dispatch is not a no-op in the TCB — the wrapper must make it one

`record_verdict` appends unconditionally; a second dispatch for an
already-audited `change_id` writes a second `HUMAN_AUDIT` record
(`agent-core/agent_core/audit_sampler.py:61-78`). The draft's F-034 AC-3
("re-dispatch on a resolved record is a logged no-op") is currently untrue and
must not be fixed inside `audit_sampler.py` (protected, I-2). The dispatch
wrapper pre-checks the resolved view for an existing `HUMAN_AUDIT` label and
exits as a logged no-op. Two adjacent facts make F-034's dedupe AC
load-bearing rather than cosmetic: `select_for_audit` is random and
**non-persistent** (a fresh selection every run, nothing marks "already
selected"), and `per_domain_floor = 30` (`audit_sampler.py:29`) selects nearly
every record in the early low-volume regime — without issue-level dedupe the
weekly job would re-open the whole backlog every week.

### E. Credentials and fork safety

The draft prescribes "a fine-grained token" for data-branch pushes. The
default `GITHUB_TOKEN` with job-scoped `permissions: contents: write` already
pushes non-protected branches of the same repo — no new credential surface,
consistent with the repo's local-first posture; ADR 0018 should choose it and
note branch-protection exclusion for the data branch. Conversely,
`pull_request`-triggered jobs (shadow gate) must treat store sync as
**read-only** (fetch/merge, never push): fork PRs get a read-only token, and a
PR-time job has nothing legitimate to persist anyway. For the decision
surface, prefer `$GITHUB_STEP_SUMMARY` (zero extra permissions) over a sticky
PR comment (`pull-requests: write`).

### F. Cross-workflow push races

Four writers share the data branch (seed-on-merge, daily labeller, weekly
audit selector, human verdict dispatch). The existing
`concurrency: merge-gate-${{ github.ref }}` group does not serialize across
workflows or refs. The draft's fetch→rebase→push retry is the right
mitigation — v2 makes it explicit that this loop is `store_sync`'s core
correctness obligation (bounded retries, append-only merge keyed by
`change_id`+`label_source`+`labeled_at`, `HUMAN_AUDIT` never dropped), tested
against a temp bare repo with interleaved pushes (draft AC-2/AC-3 retained).

## 4. Endorsed without change

- **Backend choice (a) — dedicated data branch** — and the stated rejection
  rationale for Actions cache/artifacts (expiry ≠ accumulation) and S3
  (credential surface). Diffable, auditable, zero new deps; commit authorship
  doubles as the actor attribution trail for gap D.
- **Scope discipline**: no new metrics, no new gates, no calibration-math
  changes; TCB (I-2) treated as read-only. The one substantial new module
  (`store_sync`) sits outside the TCB.
- **Execution order** (ADR → persistence → labeller → shadow+seed → audit
  surface → soak) and the human gates at steps 1, 2, 5, 6.
- **F-036 deferral** with a `status: deferred` features.yaml entry — matching
  the existing F-008 precedent.
- **Fail-safe posture (I-3)**: every finding above was resolved in the
  fail-toward-ESCALATE/no-op direction; nothing here loosens it.

## 5. Recommendation

Adopt [`PLAN.md`](PLAN.md) (v2) as the executable plan. It preserves the
draft's structure, scope, and non-goals; corrects §2's factual errors; and
folds gaps A–F into ADR 0018's scope and the feature ACs. Do not implement
from the draft as written — F-033's AC-1 names a label source that cannot be
emitted, F-034's issue body prints a command that cannot run, and F-035 would
fail every PR it was meant to observe.

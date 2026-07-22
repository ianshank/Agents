# 0023 — Agent-confidence proxy + agent-domain seeding & backfill

- Status: **Proposed.**
- Date: 2026-07-22
- Related: ADR 0005 (calibrated merge gate), ADR 0018 (outcome-store persistence — this ADR
  supersedes its §5 "no author/branch heuristic" stance), `docs/plans/real-data-activation/PLAN.md`
  (F-032…F-035, invariants I-1…I-6), F-042 (agent seed routing + proxy), F-043 (agent-records
  calibration report), F-044 (backfill migration).

## Context

The calibrated merge gate exists to calibrate **agent-authored** changes, but after F-032…F-035
landed, its outcome store is statistically inert. Measured against `origin/merge-gate-data`
on 2026-07-22: 34 records / 25 change_ids, **every** record `domain=human/*`,
`raw_confidence=0.0`, `agent_version=null`; 9 labels (6 `timeout_clean`, 3 `ci_failure`), zero
`human_audit`.

This is the state ADR 0018 §5 recorded deliberately: `merge-gate-seed.yml` always passes
`--human`, so every landed change — agent or human — is stamped `human/<domain>` at confidence
`0.0`. With a constant predictor, calibration is degenerate: AUROC is 0.5 by construction (all
scores tie), isotonic/PAV collapses to one block, and the Brier decomposition has resolution 0.
More human records measure the degeneracy more precisely; they do not remove it. ADR 0018 §5
named `merge_gate_context.py --confidence` as the seam for a future agent-confidence artifact
and declared the agent-domain soak "plumbing-only" until one exists. This ADR fills that seam.

Two facts from the 2026-07-22 measurement shape the decision:

1. **~18 of 25 change_ids are Claude-agent-authored** (PR head branch `claude/*`); 6 are human
   (`feat/*`/`fix/*`); 1 is a direct push. Agent rows already exist in history — mislabeled as
   `human/*`.
2. **The PR author login does not distinguish agent from human.** Both a Claude PR (#72, head
   `claude/…`) and a human PR (#63, head `fix/…`) have `user.login = ianshank`. The reliable,
   deterministic signal is the **PR head-branch prefix**.

ADR 0018 §5 said "no author/branch heuristic is used, because none recovers a *real* confidence
value." That rationale is intact — but it conflated two separate questions. Identifying *which*
changes are agent-authored (a routing question) is cleanly answerable from the head-ref prefix.
Recovering a *real* agent confidence is not, so we do not claim to: we adopt an explicitly
labeled **proxy**, kept isolated in the agent domain where per-domain calibration models cannot
leak it into any human calibrator.

## Decision

### 1. Deterministic confidence proxy (not a claimed "real" confidence)

Agent-authored merges are seeded with a confidence computed by a pure, deterministic function of
merge-time signals available from git and the changed-file set:

- **lines changed** (`git diff --numstat`, added+removed),
- **files-touched count**,
- **test-file ratio** (test files / files touched),
- **`touches_protected`** (`eval_protected_paths.matched_protected`).

`mech_pass` is deliberately **excluded**: Layer 0 of `decide()` REJECTs `!mech_pass`, and the
store only seeds *merged* changes, so `mech_pass ≈ True` for every record — as a proxy input it
adds ~zero variance.

The function is a bounded monotone combination with weights and clamp bounds in a committed,
schema-validated config (`config/agent-confidence.yaml`, I-4). The output is clamped strictly
inside `(0, 1)` — never exactly `0.0` (the reserved human sentinel `_HUMAN_CONFIDENCE`) or `1.0`.
Because it is pure and reads only historical signals, the **same function** runs live at
merge time and retroactively during backfill (§4), so forward and migrated rows are computed
identically.

This proxy calibrates *the proxy heuristic*, not an agent's introspective belief. That is stated
in the module, in F-043's report output, and here: the honest expectation is **weak
discrimination (AUROC ≈ 0.5–0.65)**. The goal it serves is the one F-036/ADR 0018 §5 deferred —
a *non-degenerate* predictor so the calibration machinery can produce a real, correctly-uncertain
number — not a good one.

### 2. Head-ref-prefix routing at seed time

`merge-gate-seed.yml` (on `push: main`) resolves the merged change's PR head branch via
`gh api repos/<repo>/commits/<sha>/pulls --jq '.[0].head.ref'` and matches it against
`config/agent-authors.yaml`, a committed map of **head-ref prefixes** (and optional author
logins, for agents whose bot account *does* differ) → `agent_version`. Only `claude/ →
claude-code` is evidenced in this repo and shipped active; other agents are added when first
observed (we do not guess their branch prefixes or bot slugs).

- **Agent branch** (prefix matches): compute the proxy `p`, then
  `merge_gate_context.py --files-from … --confidence <p>` (no `--human`, so the domain stays
  un-prefixed = the agent domain) and `merge_seed … --agent-version <v>`.
- **Human / no-PR / API-failure branch:** the existing `--human` path, unchanged. Every failure
  mode (no associated PR, unmatched prefix, `gh` error) falls back to `--human` and is **logged
  loudly in the step summary** so silent under-counting of agent rows is visible (I-3).

Routing changes *where a record is filed and what confidence it carries*; it changes no gate
decision. `agent_version` remains a keying axis with zero decision effect (as in ADR 0018).

### 3. Isolation keeps the poisoning path closed (zero TCB change)

Agent records land in the un-prefixed domain (e.g. `agent-core`); human records stay in
`human/<domain>`. `build_domain_models` groups strictly by `domain`, so human `0.0` outcomes and
agent proxy outcomes never share a calibrator, `tau`, or bin — the `BinningCalibrator.predict()`
poisoning path (ADR 0018 §5, REVIEW.md §6) cannot fire. No change to the TCB
(`calibration.py`, `merge_gate.py`, `outcome_store.py`, `audit_sampler.py`) semantics (I-2).
In particular `audit_sampler.record_verdict` is **not** modified to carry `agent_version`
forward; F-043's report recovers it by joining a `HUMAN_AUDIT` row to its seed record by
`change_id`.

### 4. One-time reversible backfill (correction of a known mislabel)

The ~18 already-merged agent SHAs were seeded as `human/*` at `0.0` by the `--human`-only
workflow — a known mislabel, not fabricated data. A one-off migration (F-044) re-domains **all**
records of each hand-verified agent SHA from `human/<d>` → `<d>`, recomputing the proxy over the
historical diff and setting `agent_version`. Because the store is append-only and idempotent by
`change_id`, correction requires rewriting the canonical store file (via `store_sync`'s
git-plumbing write path and canonical ordering, ADR 0018 §4), not appending.

This is the only operation that rewrites store history. Its safety envelope:
- input is a **committed, hand-verified** SHA list (classified from the merge-commit head-ref
  prefix), not a live guess;
- the `merge-gate-data` branch is **tagged/snapshotted before apply** (reversible);
- **dry-run by default**, printing the full before/after diff; `--apply` is required;
- it **never touches `HUMAN_AUDIT`** and refuses any SHA already carrying one;
- it is idempotent (re-running yields a byte-identical store);
- a human reviews the dry-run diff before apply.

## Consequences

- The agent domains leave cold-start with a *varying* confidence, so F-043 can emit a real
  calibration curve (ECE, Brier decomposition, AUROC, abstention, Wilson CIs) instead of a
  degenerate point mass. The curve will be weak and wide at first (N≈18–30, human audits ≈10–15);
  that is expected and must be labeled, not hidden.
- **Auto-merge is not enabled.** `ENABLE_CALIBRATED_AUTOMERGE` stays a human checklist item
  (ADR 0005), and the in-code trustworthiness floor `min_calibration_n = 200` means `tau` cannot
  activate on this volume regardless. The deliverable is the honest report, not the green light.
- No new label sources, metrics, or gate policy; the four `LabelSource` values and `calibration.py`
  are reused unchanged (I-1, I-6).
- F-035's second "`human/<domain>` observability decision" covers fewer of the interesting
  records as audits move into agent domains — expected, non-breaking.
- Adding a new agent (Devin/Codex/Copilot) is a config-only change once its head-ref prefix or
  bot login is observed in this repo.

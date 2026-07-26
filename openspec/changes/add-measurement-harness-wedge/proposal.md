# Change: add-measurement-harness-wedge

**Status:** proposed · **Date:** 2026-07-26 · **Author track:** `claude/` agent lane
**Motivated by:** `./review.md` (peer review of the "add-business-readiness-wedge" proposal)
**Compiles down to:** `docs/plans/<topic>/PLAN.md` + F-IDs (claimed at land) + a design ADR.

## Why

The system has strong internal validation and no external evidence. The prior proposal
(`add-business-readiness-wedge`) tried to fix that by pulling a public `merge_gate_report` CLI
forward and marketing "calibrated confidence for agent-written PRs." The peer review in
`./review.md` found that framing undeliverable, on this repo's own documented terms:

- `raw_confidence` is a **diff-shape heuristic**, not an agent's belief
  (`scripts/agent_confidence.py:11-14`, ADR 0023 §1).
- ADR 0023 §1 puts its honest expected discrimination at **AUROC ≈ 0.5–0.65**, while the gate's
  own health floor is `min_auroc = 0.65` (`merge_gate.py:49`). The only shipped confidence
  signal is predicted, in writing, to fail the system's own trustworthiness gate.
- Only `HUMAN_AUDIT` labels feed `tau`/health (ADR 0005 §3-4), and the live store holds
  **zero** of them across 46 records — all 8 agent-domain rows are entirely unlabelled.
- `GatePolicyConfig` is unreachable from any config file or CLI flag (G1,
  `docs/gap-analysis-merge-gate-2026-07-24.md`), so an external party cannot even re-tune the
  risk appetite that sets the bar.

A design partner running that today receives *no tau, cold-start, escalate-everything*, with no
measured discrimination at all. That is worse than shipping nothing: it spends a warm intro on
a demo that structurally cannot show value, and stakes the differentiating claim
("calibration, not vibes") on the one number the evidence does not support.

This change ships the honest version of the same wedge — the **measurement harness**:

> Point it at your agent-PR history and it tells you whether your merge-risk signal has any
> discriminative power at all — with honest uncertainty, and explicit degeneracy reporting
> instead of a fabricated number.

That claim is true today, it is differentiated (Langfuse/Braintrust/Arize do not do calibration
diagnostics on merge decisions), and it generates the audit data that makes the calibrated gate
real later — which is what makes it a wedge rather than a demo.

## What changes

- **WS-0 (blocking): hygiene gate.** Redact the still-live Langfuse key pair from three tracked
  files, land a fail-closed gitleaks gate, and correct `SECURITY.md`, which currently asserts
  two controls that do not exist. Salvaged by rebase from the stranded `feat/F-038-gitleaks`.
- **WS-1: external PR-history ingestion** behind a `PRHistorySource` Protocol —
  `LocalGitSource` (fully offline) and `GhCliSource` (reusing `run_failsafe`, inheriting auth
  and pagination from `gh`). Partner-supplied attribution rules are first-class, not this
  repo's `claude/`-only defaults.
- **WS-2: an honest report surface.** An AUROC **confidence interval** (none exists in the repo
  today), a truth-side selector so passive labels can serve as ground truth, a self-contained
  static HTML renderer that leads with degeneracy, and the G3 fix so "no data" stops reading as
  strongest evidence.
- **WS-3: distribution.** First `[project.scripts]` entry for `agent-core`, pipx-installable
  from a git ref.
- **WS-4: external shadow mode** — a thin delta reusing the existing log-only path.
- **WS-5: positioning** — an *additive* README section, quickstart, and one committed sample
  report showing its degeneracy findings honestly.

## Scope / non-goals

- **Non-goal: any gate change.** `merge_gate.decide()`, `tau`, `min_calibration_n`,
  `wilson_floor`, and the ADR 0005 enablement checklist are untouched. Auto-merge stays off.
  The one TCB edit (G3) is additive, strictly fail-closed, and isolated to its own PR.
- **Non-goal: a new reporting CLI.** `calibration_report` (F-043) already ships one, and
  `docs/plans/agents-critical-path/REVIEW.md:30` already rejected a parallel
  `merge_gate_report` as duplicative. This change extends what exists.
- **Non-goal: laundering passive labels as `HUMAN_AUDIT`.** ADR 0005 §4 forbids it,
  `outcome_store.py:226` enforces it, and ingestion results stay DIAGNOSTIC (not tau-eligible).
- **Non-goal: LLM involvement.** External PR content is an untrusted prompt-injection surface;
  the harness is statistical only. This also preserves the air-gap/self-hosted story.
- **Deferred:** `GitHubRestSource` (v2 — `GhCliSource` covers the wedge at a fifth the surface);
  auto-merge write paths; Braintrust/SpecKit bake-offs.
- **Human-owned, blocking:** rotation confirmation (WS-0), a CHARTER §3 amendment with
  GOVERNANCE sign-off (the wedge expands scope past *"not an autonomous merge bot"*), and a
  package rename — `langfuse-eval-harness` and `claude-foundation-tools` are third-party marks
  and Apache-2.0 §6 grants no trademark license.

## Impact

- New F-IDs and an ADR, **claimed at land** (next free today: F-048, ADR 0027). Every ID the
  2026-07-03 plan pre-assigned drifted; `openspec/project.md:34` exists because of it.
- Source: new `agent-core/agent_core/pr_history/` subpackage, `discrimination.py`,
  `calibration_report_html.py`, `scripts/pr_ingest.py`; additive fields in `report_types.py`;
  a one-line fail-closed fix in `outcome_store.py`.
- Protected steps (isolated commits, `eval-change-approved` + CODEOWNERS): all test files —
  `scripts/eval_protected_paths.py:29-46` protects every sibling `tests/**` — plus
  `features.yaml`, `scripts/validations/**`, and `.github/**`.
- Invariants preserved: I-1 (no automated `HUMAN_AUDIT` write), I-2 (TCB carve-out), I-3
  (fail-safe to escalate), I-4 (no call-site literals). New invariant: all externally ingested
  repository text is untrusted data — parsed structurally, rendered escaped, never interpreted
  as instructions and never passed to a model.

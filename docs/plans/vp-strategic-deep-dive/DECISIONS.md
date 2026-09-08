# Leadership decisions — VP strategic roadmap

**Date:** 2026-09-06 · **Status:** recommended defaults (operator may retune)
**Context:** [EXECUTIVE_BRIEF.md](EXECUTIVE_BRIEF.md) · [ANALYSIS.md](ANALYSIS.md)

These are **recorded recommendations**, not GitHub settings changes and not a CHARTER
amendment. An agent cannot enable branch protection, invent HUMAN_AUDIT labels, or
ratify scope expansion. The code in this change makes the recommendations *operable*
(config overlays, soak progress, provenance floors) without pretending they are done.

## 1. Merge-gate risk appetite

**Question:** Is ~380 near-perfect HUMAN_AUDIT records per domain an acceptable
activation cost? What `max_bin_ci_width`?

**Recommended default: staged per-domain activation (option C), shadow until then.**

| Knob | Default | Where it lives |
|---|---|---|
| Activation bar | `SoakConfig.target_per_domain` (380) | `agent_core.config.SoakConfig` |
| Health floors | `GatePolicyConfig` (`min_calibration_n=200`, `max_ece=0.05`, `min_auroc=0.65`, `max_bin_ci_width=0.20`) | dataclass; overlay via `MERGE_GATE_*` / `--policy-file` |
| Auto-merge | off | `vars.ENABLE_CALIBRATED_AUTOMERGE` must stay unset/false |

Rationale: waiting for every domain in serial (option A) is calendar-bound to
maintainer merge velocity, not engineering. Enabling a blocking gate on thin data
(option B as *blocking*) would make `tau` from TIMEOUT_CLEAN-shaped optimism. Shadow
mode already runs on every PR; a domain graduates when *that domain's* HUMAN_AUDIT
count and health floors clear, independently of siblings.

`protected_auto_merge` stays unreachable from CLI/env/file (ADR 0005). Setting
`MERGE_GATE_PROTECTED_AUTO_MERGE` fails the gate closed (`ConfigError`, exit 2).

## 2. Second collaborator / Code-Owner review

**Question:** Is adding a second collaborator with Code-Owner rights viable?

**Recommended default: add a second maintainer when feasible; keep Code-Owner
review deferred until then.**

ADR 0037 already records the deadlock: GitHub will not let a pull-request author
approve their own PR, and the sole collaborator is the sole CODEOWNER. Branch
protection with **required status checks only** (no review requirement) is the
unblocking admin action — see [branch-protection-enablement.md](../../runbooks/branch-protection-enablement.md).
`scripts/check_branch_protection.py` reports the derived check set; it cannot flip
the GitHub setting.

## 3. CHARTER scope (production eval flywheel)

**Question:** Should production-trace → golden-dataset ingestion be ratified into
CHARTER §3?

**Recommended default: defer. Do not amend `docs/CHARTER.md`.**

`openspec/changes/add-production-eval-flywheel/` stays **blocked** on a human
ratification plus its own ADR. CHARTER §3 lists "a general observability platform"
as a non-goal; sneaking ingestion in through a feature branch would violate the
invariants gate. Revisit only after Streams 1–2 are load-bearing (required checks
on `main`, at least one domain with a measured HUMAN_AUDIT velocity).

## 4. Judge labeling investment

**Question:** Who labels the golden corpus? What adjudication protocol?

**Recommended default: two annotators, escalate-on-tie, Landis–Koch substantial
kappa (0.60), first corpus floor 50 human-labeled items.**

Protocol is code, not prose: `LabelingProtocolConfig`, `CorpusProvenanceConfig`,
`JudgeBaselineConfig`. See [labeling-protocol.md](../../runbooks/labeling-protocol.md)
and [golden-corpus/README.md](../../golden-corpus/README.md). **This repository
ships zero synthetic stand-ins for those 50 labels.** A corpus without
`meta.provenance=human` cannot underwrite a blocking judge-backed gate.

## 5. Measurement-wedge WS-1 vs CHARTER (house-doc disagreement)

**Question:** May `LocalGitSource` / `agent_core/pr_history/` (wedge WS-1) land without a
CHARTER §3 amendment?

**Status: unresolved. Do not implement WS-1 until this is decided here, not in a
feature branch.**

House documents currently disagree:

| Document | Claim |
|---|---|
| `openspec/changes/add-measurement-harness-wedge/tasks.md` H.2 | A CHARTER §3 amendment + GOVERNANCE sign-off **blocks remaining phases** (the wedge expands scope past "not an autonomous merge bot… not a general observability platform"). H.2 is listed as blocking WS-5; WS-1 is written as if it can proceed as diagnostic ingest that cannot write `HUMAN_AUDIT`. |
| `docs/plans/eval-delivery-sequencing/PLAN.md` | Remaining wedge blockers are **governance** (CHARTER amendment, rotation confirmation, package rename). An earlier revision also listed WS-1 as genuinely unblocked. |
| Post-216 sequencing | Weaker reading: diagnostic ingest that cannot write `HUMAN_AUDIT` is charter-free; stronger reading: any external PR-history ingestion is the observability-platform non-goal. |

This is a **house-doc disagreement**, not a closed legal question. The weaker reading
(diagnostic ingest, no `HUMAN_AUDIT` writer) is not an implementation licence.
After Deck B, the XOR is eval-evidence Phase 9 (fleet matrix) **or** WS-1 once this
note is decided. Neither is in the F-069 change.

## 6. Operator remaining after PR #216 (human-only)

These are not agent-completable. Recording them here is the honest close-out.

### 6a. Branch protection (ADR 0037)

`scripts/check_branch_protection.py` derives **23** required contexts. This session's
`--probe` returns `gh: Resource not accessible by integration (HTTP 403)`. Live
`"protected": false` is last attested in [PR #216](https://github.com/ianshank/Agents/pull/216),
not re-GET'd here. ADR 0037 asks for **five** green runs per context before `--apply`;
#216 documented one soak of two workflows. Confirm five greens (or record an explicit
weaker soak), then:

```bash
python scripts/check_branch_protection.py --apply --repository ianshank/Agents
python scripts/check_branch_protection.py --probe --repository ianshank/Agents
```

Leave `merge-gate-data` unprotected. Do not wire `--strict` into CI until a successful
probe. Tick ADR 0037 Accepted only after `protected=true`.

### 6b. Audit queue (issues #200–#215)

`merge-gate-verdict.yml` is the **only automated writer** of `HUMAN_AUDIT`
(`workflow_dispatch` only; F-034). Library `record_verdict` exists; agents must not
use it on the live store. 16 open `merge-gate-audit` issues vs 99 unlabelled pending:
draining the current queue does **not** change `SoakConfig.remaining_by_domain` (380
HUMAN_AUDIT per decision domain). `human/*` twins are auditable on purpose and isolated
from agent-domain calibration — do not read 15×380 as the automerge bar.


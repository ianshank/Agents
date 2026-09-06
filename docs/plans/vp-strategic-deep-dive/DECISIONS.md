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

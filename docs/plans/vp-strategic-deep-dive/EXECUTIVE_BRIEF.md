# Executive Brief: langfuse-eval-harness Strategic Roadmap

**Date:** 2026-09-06 | **Version:** 1.0

---

## One-Line Summary

The codebase is **feature-complete** (64/66 shipped); value delivery now depends on **operational activation** requiring human audit labels and branch protection enablement.

---

## Current State

| Dimension | Status | Health |
|-----------|--------|--------|
| Features | 64/66 shipped, 2 deferred | ✅ Strong |
| Test Coverage | 96-100% across all packages | ✅ Strong |
| Architecture | 43 ADRs, enforced airgaps | ✅ Strong |
| Merge-Gate Store | 165 records, 0 human-audited | ⚠️ Blocked |
| Branch Protection | None enabled | ❌ Gap |
| Human Audit Labels | 0 of ~380 needed per domain | ❌ Gap |

---

## Three Parallel Workstreams

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  STREAM 1        │  │  STREAM 2        │  │  STREAM 3        │
│  Gate Enablement │  │  Audit Accum.    │  │  Judge Validity  │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│  Owner: Admin    │  │  Owner: Human    │  │  Owner: Human    │
│  Timeline: 2-4w  │  │  Timeline: 6+mo  │  │  Timeline: 2-4w  │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│  • Branch prot.  │  │  • Weekly triage │  │  • Golden corpus │
│  • G4/G5 gaps    │  │  • Verdict log   │  │  • ~50 items     │
│  • Archive debt  │  │  • Per-domain    │  │  • Adjudication  │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## Key Decisions Needed

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **Activation Strategy** | Full soak (~131d/domain) vs Advisory mode vs Staged | Staged per-domain |
| **Second Maintainer** | Add collaborator vs Accept advisory CODEOWNERS | Add if feasible |
| **CHARTER Amendments** | Production flywheel scope expansion | Defer until core active |

---

## Immediate Actions (Next 30 Days)

1. **Enable branch protection** on `main` (admin, ~1 hour)
2. **Establish weekly audit triage** (human, ongoing)
3. **Archive 5 completed OpenSpec changes** — engineering done (`openspec/changes/archive/`); merge still needs `eval-change-approved`
4. **Close G4/G5 observability gaps** — engineering done (`configure_from_config` on the four CLIs; TIMEOUT_CLEAN INFO; duplicate-audit WARNING). G7 remains out of scope.
5. **Begin golden corpus labeling** (human, parallel; infrastructure shipped, 0 items on purpose)

---

## Success Metrics

| Timeframe | Metric | Target |
|-----------|--------|--------|
| 30 days | Branch protection enabled | Yes |
| 30 days | First HUMAN_AUDIT records | >0 |
| 90 days | Golden corpus size | ≥50 |
| 180 days | First domain activated | Yes |

---

## Bottom Line

**The infrastructure is built. The statistical trust must be earned through human-labeled outcomes.**

The codebase represents mature engineering with principled architecture. No additional features are blocking value delivery. The critical path is:

1. Human action to enable branch protection
2. Sustained human investment in audit label accumulation
3. Human labeling for judge validity corpus

Engineering can accelerate Streams 1 and 3; Stream 2 requires months of sustained human audit triage that cannot be automated.

---

*Full analysis: [`ANALYSIS.md`](./ANALYSIS.md)*

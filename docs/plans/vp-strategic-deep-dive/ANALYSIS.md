# VP Strategic Deep Dive: langfuse-eval-harness Next Steps

**Date:** 2026-09-06
**Prepared by:** Strategic Analysis (7 parallel explorations + peer review)

---

## Executive Summary

This document provides a deep technical analysis for VP-level decision-making on the langfuse-eval-harness monorepo. The codebase has reached a **strategic inflection point**: 64 of 66 features shipped, 96%+ test coverage, and mature architecture — but the binding constraint for value delivery is now **operational activation**, not more features.

**Key Finding:** The merge-gate store contains **165 records with zero HUMAN_AUDIT labels**. The system needs ~380 audited records per domain for activation. At current velocity (~2.4 records/day), this represents ~131 days per domain — but this estimate carries high uncertainty given single-maintainer operations.

---

## 1. Current State: Quantified

### 1.1 Codebase Health Metrics

| Metric | Value | Gate |
|--------|-------|------|
| Total features tracked | 66 | — |
| Features shipped (done) | 64 | — |
| Features deferred | 2 (F-008, F-036) | — |
| Root package coverage | 96%+ | ≥96% |
| agent-core coverage | 95.58% | ≥95% |
| flow-corpus coverage | 100% | ≥95% |
| flow-protocol coverage | 100% | ≥95% |
| behavioral-regression coverage | 100% | ≥95% |
| ADRs documented | 43 | — |
| Skills in marketplace | 15 | — |

### 1.2 Merge-Gate Store Analysis (Live Data)

```
Total records: 165
Date range: 2026-07-03 to 2026-09-06

By label status:
  PENDING (no label): 100
  PASSIVE (automated): 65
  HUMAN_AUDIT: 0          ← CRITICAL GAP

By domain (top 10):
  agent-core: 32
  eval-harness: 20
  human/agent-core: 18
  human/tooling: 14
  tooling: 14
  human/eval-harness: 12
  skills: 10
  human/ci-config: 9
  docs: 9
  human/skills: 8

Agent versions:
  None (human): 116
  claude-code: 49
```

**Implication:** The merge-gate decision logic is complete and running in shadow mode, but cannot activate because zero human-audited records exist. The ~380 records per domain requirement means:

- At 2.4 records/day velocity, ~131 days per domain
- With 15 domains, sequential activation would take years
- Parallel accumulation requires sustained human audit triage

### 1.3 OpenSpec Change Pipeline

| Status | Count | Changes |
|--------|-------|---------|
| **Implemented, pending archive** | 5 | prove-m8-execution, extend-judge-calibration, add-repeat-reliability-metrics, add-gate-decision-provenance, add-testgen-eval-matrix |
| **Proposed, in progress** | 3 | add-agent-in-the-loop-testgen, add-rca-eval-matrix, add-requirements-gen-eval-matrix |
| **Partially implemented** | 1 | add-measurement-harness-wedge (WS-0 done as F-048) |
| **Blocked** | 1 | add-production-eval-flywheel (requires CHARTER §3 amendment) |
| **Archived (complete)** | 12 | F-047 through F-060, plus non-feature changes |

---

## 2. Critical Path Analysis

### 2.1 The Real Activation Blockers

```
┌─────────────────────────────────────────────────────────────┐
│  BLOCKER 1: Branch Protection (Human Action Required)       │
│  ─────────────────────────────────────────────────────────  │
│  Status: main has NO branch protection (verified via API)   │
│  Impact: All 16 CI workflows are advisory, not enforced     │
│  Fix: GitHub settings change (ADR 0037 ready)               │
│  Owner: Admin with repository access                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  BLOCKER 2: Human Audit Labels (Zero Currently)             │
│  ─────────────────────────────────────────────────────────  │
│  Required: ~380 near-perfect audits per domain              │
│  Current: 0 HUMAN_AUDIT records across all domains          │
│  Fix: Weekly audit triage + human verdict recording         │
│  Owner: Human reviewer (cannot be automated)                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  BLOCKER 3: Single-Maintainer Constraint                    │
│  ─────────────────────────────────────────────────────────  │
│  Issue: CODEOWNERS requires @ianshank, who is sole owner    │
│  Impact: Code-Owner review is structurally impossible       │
│  Fix: Add second collaborator OR accept advisory-only mode  │
│  Owner: Repository owner                                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Eval Evidence Integrity Plan Status

| Phase | Focus | Status | Dependency |
|-------|-------|--------|------------|
| 0 | Publish honest baseline | **DONE** | — |
| 1 | Branch protection + coverage gate fix | **PARTIAL** (gate fix done; GitHub settings human/out-of-band) | Phase 0 |
| 2 | M8 = execution, not config presence | **DONE** (prove-m8-execution) | Phase 1 |
| 3 | Breadth to 19 test-only components | **DONE** (39/41 credited) | Phase 2 |
| 4 | `client=` DI seams on network judges | **DONE** (F-063) | — |
| 5 | Live-provider smokes | **PLANNED** | CI credentials |
| 6 | Judge-gate authorization | **DONE** (F-066) | — |
| 7 | Golden/pairwise corpus with human labels | **OPEN** ← Critical path | Human labeling |
| 8 | E2E matrix provenance repair | **PLANNED** | Phase 2 |
| 9 | Extend matrix to sibling packages | **PLANNED** | Phase 2 semantics |
| 10 | Depth canaries | **PLANNED** | — |

---

## 3. Strategic Recommendations

### 3.1 Immediate Actions (0-30 days)

#### Action 1: Enable Branch Protection
- **What:** Configure required status checks on `main` per ADR 0037
- **Who:** Repository admin (out-of-band GitHub settings)
- **Checks to require:** quality-gates, eval-harness-ci, 4 package CIs, architecture-drift
- **Risk:** Test each check 5x on main before requiring (flaky check = repo bricked)

#### Action 2: Establish Audit Triage Cadence
- **What:** Weekly schedule for `audit_sampler select` + human verdict recording
- **Who:** Human reviewer with domain expertise
- **Process:**
  1. Run `python -m agent_core.outcome_labeller` (passive labels)
  2. Run `python -m agent_core.audit_sampler select --floor 30` (sample selection)
  3. Human reviews sampled changes, records verdict via `audit_sampler record`

#### Action 3: Archive Completed OpenSpec Changes
- **What:** Move 5 "implemented, pending archive" changes to archive
- **Who:** Engineering (requires `eval-change-approved` label)
- **Changes:** prove-m8-execution, extend-judge-calibration, add-repeat-reliability-metrics, add-gate-decision-provenance, add-testgen-eval-matrix

#### Action 4: Close G4/G5 Observability Gaps
- **What:** Add `configure_logging` calls to 4 CLI entry points
- **Who:** Engineering
- **Impact:** Audit trail completeness before merge-gate activation

### 3.2 Medium-Term Actions (30-90 days)

#### Action 5: Begin Golden Corpus Labeling (Phase 7)
- **What:** Assemble ~50 items with real human labels for judge calibration
- **Who:** Human labeler(s) with domain expertise
- **Protocol needed:**
  - Item selection criteria
  - Adjudication rules for disagreements
  - Target Cohen's κ threshold
- **Why parallel:** Independent of infrastructure work; can start immediately

#### Action 6: Complete Evidence Integrity Phases 5, 8, 9
- **What:** Live-provider smokes, E2E matrix repair, fleet extension
- **Who:** Engineering
- **Dependencies:** Phase 5 needs CI credentials; Phases 8-9 need Phase 2 complete

#### Action 7: Ship `test-completeness-guard` Skill
- **What:** Generator skill for test scaffolding
- **Who:** Engineering
- **Value:** Reduces cost of maintaining 96%+ coverage floor across fleet

### 3.3 Strategic Decisions Required

#### Decision 1: Merge Gate Activation Strategy
**Options:**
| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A | Wait for full soak (~380 audits/domain) | Maximum statistical confidence | ~131+ days per domain |
| B | Advisory mode first | Faster feedback loop | Less confidence in decisions |
| C | Per-domain staged activation | Incrementally earn trust | Operational complexity |

**Recommendation:** Option C — enable advisory mode immediately, activate domains as each reaches threshold.

#### Decision 2: Single-Maintainer Constraint
**Options:**
| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A | Add second collaborator | Enables Code-Owner review | Organizational change |
| B | Accept advisory-only CODEOWNERS | No change needed | Review intent not enforced |
| C | Admin bypass for self-approval | Unblocks reviews | Defeats review purpose |

**Recommendation:** Option A if feasible; otherwise Option B with documented rationale.

#### Decision 3: CHARTER Scope Amendments
**Blocked items requiring human decision:**
- `add-production-eval-flywheel` — requires CHARTER §3 amendment (scope expansion)
- Real-incident RCA corpus — requires CHARTER §4 invariant 7 relaxation

**Recommendation:** Defer until core activation is complete; these are enhancements, not prerequisites.

---

## 4. Risk Assessment

### 4.1 Timeline Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Audit velocity stalls | HIGH | HIGH | Establish formal triage cadence |
| Single-maintainer availability | MEDIUM | HIGH | Add second collaborator |
| Branch protection flakiness | LOW | HIGH | Soak each check 5x before requiring |
| Protected-path label delays | MEDIUM | MEDIUM | Batch protected-path PRs |

### 4.2 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Judge validity gap persists | MEDIUM | HIGH | Parallel Phase 7 (golden corpus) |
| God-file accumulation | LOW | MEDIUM | Schedule protected-path split |
| autoevals security surface | LOW | MEDIUM | ADR 0039 follow-up |

---

## 5. Success Metrics

### 5.1 30-Day Targets
- [ ] Branch protection enabled on `main`
- [ ] G4/G5 observability gaps closed
- [ ] Weekly audit triage cadence established
- [ ] First HUMAN_AUDIT records in store

### 5.2 90-Day Targets
- [ ] Golden corpus: ≥50 labeled items
- [ ] HUMAN_AUDIT records: measurable velocity across domains
- [ ] Evidence integrity Phases 5, 8, 9 complete
- [ ] Advisory merge-gate mode running

### 5.3 180-Day Targets
- [ ] First domain reaches activation threshold
- [ ] Merge-gate decisions trusted for low-risk domains
- [ ] `claude-foundation` extracted to standalone repo

---

## 6. Appendix: Domain-Specific Activation Timeline

Assuming current velocity continues (~2.4 records/day) and parallel accumulation across domains:

| Domain | Current Records | Estimated Days to 380 |
|--------|-----------------|----------------------|
| agent-core | 32 | ~145 |
| eval-harness | 20 | ~150 |
| human/agent-core | 18 | ~151 |
| human/tooling | 14 | ~152 |
| tooling | 14 | ~152 |
| human/eval-harness | 12 | ~153 |
| (others) | <10 each | ~155+ |

**Caveat:** These estimates assume constant velocity and parallel audit accumulation. Real-world factors (vacations, context switches, domain expertise availability) will extend these timelines significantly.

---

## 7. Conclusion

The langfuse-eval-harness codebase is **architecturally complete** for its stated mission. The infrastructure for calibrated merge gates, behavioral regression detection, and eval evidence integrity is built and running. The binding constraint is now **operational activation** — specifically:

1. **Branch protection** (admin action, ~1 hour)
2. **Human audit labels** (sustained human investment, ~6+ months)
3. **Golden corpus for judge validity** (labeling effort, ~2-4 weeks)

The recommended strategy is to **parallelize these three workstreams** rather than treating them as sequential. Engineering can complete the remaining evidence integrity phases while humans accumulate audit labels and build the golden corpus.

**The codebase is ready. The data must be earned.**

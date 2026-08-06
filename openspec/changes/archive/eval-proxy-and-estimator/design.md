# Design: eval-proxy-and-estimator

Technical design for the change. Promotes to a numbered ADR at land (next-free number;
verify — 0026 is being consumed by the agent-record-decontamination plan). Format follows
the house ADR idiom (Context / Decision / Consequences).

## Context

The calibrated merge gate stacks four Wilson-lower gates (evidence in `./review.md` §2):

| Gate | Rule | All-correct n to clear |
|---|---|---|
| `tau` exists (`merge_gate.py:111-133`) | kept-set `acc_lower ≥ 0.98`, on the held-out fold | ~380 total audits |
| per-bin floor (`merge_gate.py:170-171`) | operating bin `acc_lower ≥ 0.90` | ≥35 / bin |
| `bin_ci_width ≤ 0.20` (`outcome_store.py:172-186`) | tight upper-half bins | tens / bin |
| `n ≥ 200` (`merge_gate.py:47`) | health floor | 200 |

A variance-reduction estimator (PPI/PPI++) helps a **mean** by `n_eff/n ≈ 1/(1−ρ²)`,
`ρ = corr(proxy, correctness)`. Two facts decide its value here:

1. The gate's binding quantities are **conditional** means on subsets where the natural
   proxy (calibrated confidence) is near-constant by construction → conditional ρ→0 → gain→0.
2. On the **unconditional** report estimates the gain is real but modest at the system's
   `min_auroc=0.65` floor (ρ≈0.3 → ~1.1×).

Therefore the design leads with **measuring which proxy has conditional signal**, treats the
estimator swap as a report-only honesty upgrade, and makes the sampler PPI-ready.

## Decision

### 1. WS-A — `agent_core.proxy_eval` (new, pure, dependency-free)

- Input: the `OutcomeStore` resolved records, joined by `change_id` to recover each proxy
  value alongside the authoritative HUMAN_AUDIT label (the join already used at
  `calibration_report.py:19-21`).
- Proxies evaluated: `raw_confidence` (baseline); passive-label agreement
  (REVERT/CI_FAILURE ⇒ incorrect, TIMEOUT_CLEAN ⇒ optimistic-correct — `outcome_store.py:33-37`);
  optional external LLM-judge score supplied as a column (not fetched here — measurement is
  offline).
- Outputs, per proxy: marginal `ρ` and `AUROC` (reuse `calibration.auroc`), **conditional**
  `ρ` on the gated subsets (score ≥ candidate `tau`; and per confidence bin), and the implied
  `1/(1−ρ²)` effective-N multiplier. Degenerate slices reported as such (mirrors
  `calibration_report`'s DEGENERATE handling), never a misleading 0.5.
- Deliverable: a dated `docs/calibration-proxy-correlation-YYYY-MM.md` snapshot (dated-prose
  idiom, not baseline JSON — the store moves daily), with store SHA + measured-at.
- No `*Config` numeric literals at call sites; bin count / z come from a `ProxyEvalConfig`
  dataclass mirroring `ReportConfig`.

### 2. WS-B — `selection_propensity` on `OutcomeRecord`

- Add `selection_propensity: float | None = None` (`outcome_store.py:40-52`).
  **Backward-compatible by construction:** `from_json` already tolerates unknown/missing
  fields (ADR 0025, commit `6299583`), so old lines load with `None` and newer writers do not
  break older readers.
- `select_for_audit` (`audit_sampler.py:32-58`) computes the exact per-domain-round marginal
  inclusion probability `p = min(1, k/N) + (1 − min(1, k/N))·base_rate` (with `k` the floor
  need, `N` the domain candidate count) and returns `(change_id, p)`; `record_verdict`
  (`:61-78`) stores `p` on the HUMAN_AUDIT record. `base_rate`/`per_domain_floor` stay on
  `AuditConfig` — no new literals.
- Rationale: enables an HT `1/p` weight (corrects the floor's over-sampling of low-volume
  domains) and is the prerequisite for any future active/non-uniform sampling. It changes no
  gate decision today.

### 3. WS-C — `ppi_plus_interval` + `--estimator` dual-report

- `agent_core.calibration.ppi_plus_interval(labeled_pairs, proxy_unlabeled, z)`:
  power-tuned PPI++ for the mean correctness `θ`:
  `θ̂ = mean_L(Y) + λ·(mean_U(f) − mean_L(f))`, with `λ∈[0,1]` chosen to minimize the
  plug-in variance (λ=0 ⇒ classical labeled-only, guaranteeing "no worse than Wilson"
  asymptotically). Returns `(point, lo, hi)`. Dependency-free; clamp λ (finite-sample guard,
  per `./review.md` "Claims confirmed accurate" — at n≈12 λ is itself noisy).
- `ReportConfig` (`calibration_report.py:54-74`) grows `estimator: str = "wilson"`, validated
  in `__post_init__` like `z`. `analyze_slice` (`:95`) computes the chosen interval beside the
  existing `wilson_interval` (`:130`) and `SliceReport` carries **both**, so the report
  dual-displays Wilson and PPI++ and the gain is visible empirically. CLI flag at `:350`.
- Scope: the report's **unconditional** estimates only. `merge_gate` continues to call
  `wilson_interval` unchanged.

## Consequences

- **Positive:** the ρ measurement answers the roadmap's Phase 4 AUROC question with power and
  decides whether PPI is worth wiring; the sampler becomes PPI-ready irreversibly-cheaply; the
  report gains an honest tighter interval without risking the gate.
- **Negative / accepted:** three new F-IDs + proofs and one protected-path PR (workflow
  emission). WS-C adds a second interval column reviewers must read as report-only.
- **Explicitly not changed:** the gate, `tau`, the four Wilson thresholds, auto-merge
  posture. Any change to `risk_target`/`wilson_floor` is a separate risk-appetite ADR.
- **Reversibility:** WS-A is read-only; WS-B is additive/nullable; WS-C defaults to `wilson`.
  Reverting is field/flag removal, no data migration.

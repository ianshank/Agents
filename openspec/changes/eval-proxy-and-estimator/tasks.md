# Tasks: eval-proxy-and-estimator

Ordered per `./review.md` §"Reprioritized recommendations". Owners use the fleet contract in
`openspec/AGENTS.md`. `[P]` = protected path → isolate into its own PR with
`eval-change-approved` + CODEOWNERS. Coverage floor: `make -C agent-core check` ≥ 95%.

## WS-A — Proxy-correlation measurement (centerpiece; do first)

- [x] Scaffold `agent-core/agent_core/proxy_eval.py` (pure) + `ProxyEvalConfig` dataclass
      (bins, z; no call-site literals).
- [x] Join resolved records → `(proxy_value, HUMAN_AUDIT label)` per `change_id`
      (reuses the pattern at `calibration_report.py:19-21`).
- [x] Compute marginal ρ/AUROC (reuses `calibration.auroc`) and **conditional** ρ on
      `score ≥ candidate-tau` and per-bin subsets; emits `1/(1−ρ²)`. Degenerate slices flagged.
- [x] Proxies: `raw_confidence`, `passive_label`, and `MappingProxy` — the pluggable
      `ProxyExtractor` seam for an external LLM-judge column (`--judge-scores`), so the
      `eval_harness` judges / `model-bench` / `SyntheticJudge` need no coupling here.
- [x] Tests in `agent-core/tests/test_proxy_eval.py` (54 cases).
- [ ] Emit dated `docs/calibration-proxy-correlation-YYYY-MM.md` (store SHA + measured-at)
      — **blocked on real data**: the live store still holds 0 `human_audit` rows, so this
      waits on the decontamination plan's Phase 2 verdicts.
- [ ] `[P]` F-ID + `scripts/validations/F_0NN.py` asserting the metric + degeneracy handling.

## WS-B — Log audit-selection propensity (prerequisite; cheap)

- [x] Added `selection_propensity: float | None = None` to `OutcomeRecord`; old lines load
      as `None` (ADR 0025 compat, locked by a test).
- [x] `select_for_audit_detailed` returns `(change_id, domain, propensity)`;
      `record_verdict(..., selection_propensity=)` stores it, validated at the write
      boundary. `select_for_audit` keeps its exact signature, selection, and RNG order.
- [x] Tests: p bounds; round-trip; legacy-record compat; seeded selection identical to the
      pre-change sampler; out-of-contract values rejected.
- [ ] `[P]` emit propensity in `.github/workflows/merge-gate-audit.yml`; F-ID + `F_0NN.py`.

## WS-C — Dual-report `--estimator {wilson, ppi++}` (report-only)

- [x] `ppi_plus_interval` in `calibration.py` (power-tuned λ clamped; λ=0 ⇒ classical;
      fail-closed to Wilson on every untrustworthy path) + `pearson_r`,
      `effective_n_multiplier`.
- [x] `ReportConfig.estimator` validated like `z`; threaded through `analyze_slice`;
      `SliceReport.ppi` defaulted; per-slice unlabeled pools; CLI flag; dual rendering.
- [x] Tests: ρ=0 ⇒ PPI++ == classical exactly; high ρ ⇒ strictly narrower; degenerate ⇒
      exactly Wilson (property-tested); Wilson columns provably unchanged.
- [ ] `[P]` F-ID + `F_0NN.py`. CHANGELOG entry — **done**.

## Measured result (synthetic soak, 400 merges / 23 audits)

Confirms the review's ordering — the proxy is the lever, not the estimator:

| approach | half-width | vs Wilson |
|---|---:|---:|
| Wilson (status quo) | 0.1508 | 1.00x |
| PPI++ with `raw_confidence` | 0.1402 | 1.08x |
| PPI++ with `passive_label` | 0.0925 | **1.63x** |

`raw_confidence` also shows the predicted restriction of range: marginal ρ=0.48 (1.30x)
collapsing to degenerate / 1.00x on every `score >= tau` subset.

## Follow-on (separate change; not this one)

- [ ] Risk-appetite ADR on `risk_target`/`wilson_floor` (policy lever, no math).
- [ ] Multi-task PPI / active / stratified / shrinkage — gated on ≥3 populated cells + a
      measured ρ from WS-A.

## Archive

- [ ] Each F-ID lands with `status: done` + `implemented_in:<sha>`; `scripts/validate.py
      --tier fast` green; `make check-all` green; then move this change under
      `openspec/changes/archive/`.
- [ ] Evaluate the OpenSpec spike per `docs/openspec-spike.md` (keep vs `rm -rf openspec/`).

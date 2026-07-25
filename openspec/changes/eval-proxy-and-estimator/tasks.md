# Tasks: eval-proxy-and-estimator

Ordered per `./review.md` §"Reprioritized recommendations". Owners use the fleet contract in
`openspec/AGENTS.md`. `[P]` = protected path → isolate into its own PR with
`eval-change-approved` + CODEOWNERS. Coverage floor: `make -C agent-core check` ≥ 95%.

## WS-A — Proxy-correlation measurement (centerpiece; do first)

- [ ] Scaffold `agent-core/agent_core/proxy_eval.py` (pure) + `ProxyEvalConfig` dataclass
      (bins, z; no call-site literals). — *general-purpose sub-agent*
- [ ] Join resolved records → `(proxy_value, HUMAN_AUDIT label)` per `change_id`
      (reuse the pattern at `calibration_report.py:19-21`). — *general-purpose*
- [ ] Compute marginal ρ/AUROC (reuse `calibration.auroc`) and **conditional** ρ on
      `score ≥ candidate-tau` and per-bin subsets; emit `1/(1−ρ²)`. Degenerate slices flagged.
- [ ] Proxies: `raw_confidence`, passive-label agreement, optional external judge column.
      Consult `eval_harness` judges / `model-bench` / `SyntheticJudge` for the judge proxy. — *measurement fleet*
- [ ] Tests to the 95% floor in `agent-core/tests/` (keep out of root `tests/**`). — *foundation:test-first*
- [ ] Emit dated `docs/calibration-proxy-correlation-YYYY-MM.md` (store SHA + measured-at).
- [ ] `[P]` F-ID + `scripts/validations/F_0NN.py` asserting the metric + degeneracy handling.
- [ ] `foundation:code-review` (forked, read-only) → then `test-runner` verify.

## WS-B — Log audit-selection propensity (prerequisite; cheap)

- [ ] Add `selection_propensity: float | None = None` to `OutcomeRecord`
      (`outcome_store.py:40-52`); confirm `from_json` old-line compat (ADR 0025). — *general-purpose*
- [ ] `select_for_audit` returns `(change_id, p)` with `p = min(1,k/N)+(1−min(1,k/N))·base_rate`;
      `record_verdict` stores `p` (`audit_sampler.py:32-78`).
- [ ] Tests: p∈(0,1]; round-trip; **old fixture without the field loads as `None`**. — *foundation:test-first*
- [ ] `[P]` emit propensity in `.github/workflows/merge-gate-audit.yml`; F-ID + `F_0NN.py`.
- [ ] `foundation:code-review` → `test-runner` verify.

## WS-C — Dual-report `--estimator {wilson, ppi++}` (report-only)

- [ ] Add `ppi_plus_interval(labeled_pairs, proxy_unlabeled, z)` to `calibration.py`
      (power-tuned λ∈[0,1] clamped; λ=0 ⇒ classical). — *general-purpose*
- [ ] `ReportConfig.estimator: str = "wilson"` (validate in `__post_init__` like `z`); thread
      through `analyze_slice` beside `wilson_interval` (`calibration_report.py:95,130`);
      `SliceReport` carries both; CLI flag (`:350`).
- [ ] Tests: ρ=0 ⇒ PPI++≈Wilson; high ρ ⇒ strictly narrower half-width; flag round-trips. — *foundation:test-first*
- [ ] `[P]` F-ID + `F_0NN.py`; CHANGELOG entry (user-visible flag).
- [ ] `foundation:code-review` → `test-runner` verify.

## Follow-on (separate change; not this one)

- [ ] Risk-appetite ADR on `risk_target`/`wilson_floor` (policy lever, no math).
- [ ] Multi-task PPI / active / stratified / shrinkage — gated on ≥3 populated cells + a
      measured ρ from WS-A.

## Archive

- [ ] Each F-ID lands with `status: done` + `implemented_in:<sha>`; `scripts/validate.py
      --tier fast` green; `make check-all` green; then move this change under
      `openspec/changes/archive/`.
- [ ] Evaluate the OpenSpec spike per `docs/openspec-spike.md` (keep vs `rm -rf openspec/`).

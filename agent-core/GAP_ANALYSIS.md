# Gap Analysis

Honest accounting of what this package does and does not do. Written so a
reviewer can see the seams deliberately, not discover them later.

## 1. Built to production quality (real logic + tests)
| Capability | Module | Tested |
|---|---|---|
| Versioned, validated, migration-aware config | `config.py`, `version.py` | yes |
| Per-run cost budget: cap / reserve / ceiling / admission | `budget.py` | yes |
| Two-gate stop logic (admission + outcome), 4 conditions | `stop.py` | yes |
| Generic verifier loop over injected nodes | `loop.py` | yes (all 4 exit paths) |
| Calibration: bins, ECE, MCE, Brier+Murphy, AUROC, Wilson, selective | `calibration.py` | yes (hand values) |
| Isotonic (PAV) recalibration | `calibration.py` | yes (monotonic + ECE↓) |
| Config-driven logging + debug tracer | `logging_util.py` | yes |
| Backwards-compat (config migration + deprecated alias) | `version.py` | yes |
| Prompt-injection sanitizer + threat-model | `sanitize.py`, `docs/sanitizer-threat-model.md` | yes |
| Golden-set construction, split, cohen_kappa, evaluate_on_split | `golden.py` | yes |
| Per-domain recalibration: TemperatureScaler, CalibratorRegistry | `recalibration.py` | yes |
| Async / parallel cycle execution with semaphore-capped fan-out | `async_loop.py` | yes |
| Run-state persistence with behavioural calibrator round-trip | `persistence.py` | yes |

## 2. Deliberate Protocol seams — interface defined, implementation NOT included
These are I/O-bound or external and would be untestable fakes if stubbed here.
The contract exists; a real implementation drops in without core changes.

| Seam | Protocol | Why not implemented here |
|---|---|---|
| Adversarial verifier | `CycleRunner` | needs a real LLM + retrieval; faking it adds untested, throwaway code |
| Cost projection | `CostEstimator` | depends on the chosen model's tokeniser/pricing |
| Source sanitizer / injection filter | `Sanitizer` Protocol in `sanitize.py` | **built** — see §1; the seam is retained so custom sanitizers can be injected |
| Retrieval, LLM gateway, claim store | — | external services / persistence |
| Eval-harness orchestration & observability sink | — | wiring layer over the metrics in `calibration.py` |

## 3. Not addressed at all
All five items from the original §3 roadmap are now built (see §1). No unaddressed
roadmap items remain from this phase.

## 4. Known limitations of what IS built
- **Isotonic recalibration is validated in-sample** in tests (proves the
  mechanism reduces ECE). Production use MUST fit on a calibration split and
  validate on an untouched test split — enforced by discipline, not by code.
- **Brier–Murphy identity is exact only for forecasts constant within a bin**;
  otherwise the decomposition equals the Brier of the *binned* forecasts. Tests
  use distinct-per-bin data to assert the exact identity.
- **AUROC uses the rank/Mann-Whitney identity** with average ranks for ties;
  undefined (raises) when only one class is present — handled as `None` in
  `evaluate_calibration`.
- **Budget admission uses a projected next-cycle cost**; accuracy of the stop
  depends entirely on the injected `CostEstimator`. A bad estimator can still
  overshoot within a single cycle — there is no intra-cycle cost interrupt.

## 5. Test coverage residual (96% branch)
Uncovered lines are defensive guards and a few unreachable-in-practice branches
(e.g. some `None`-result early returns in stop conditions, one logging fall-through).
Pushing to 100% would require asserting trivial guard lines — judged as padding
and deliberately skipped, consistent with the "no redundant code" constraint.

## 6. Redundant/unused-code audit
- No dead helpers: every public symbol in `__all__` is exercised by a test.
- Removed the unused `Number` alias during this audit; no dead helpers remain.
- The `deprecated_alias` shim is intentional surface area for compatibility, not
  dead code.

---

## 7. Revisions applied (peer-review round)
Each item below was raised by the objective self-review and is now addressed.

| Review finding | Severity | Resolution |
|---|---|---|
| Reserve/cap invariant unenforced (demonstrated breach: spent 140 vs cap 100) | Critical | `record()` now enforces a hard cap and a per-cycle allowance; loop grants `allowance = remaining_for_loop` and catches `BudgetExceededError`, finalising `BUDGET` with `overspent=True`. New test `test_lying_estimator_cannot_breach_reserve_or_cap` asserts `spent <= cap` and reserve intact. |
| No termination guarantee independent of gates | Critical | `LoopController` enforces `loop.absolute_max_cycles` regardless of injected gates → `StopReason.ABORTED`. Test `test_aborts_when_admission_gate_misconfigured`. |
| Isotonic interpolation path untested | High | Hypothesis test `test_isotonic_monotone_at_arbitrary_points` evaluates predict at non-knot grid points; monotonicity + `[0,1]` bounds verified over randomised fits. |
| "Best practices" claimed without static analysis / property tests | High | Added Hypothesis property tests (metric ranges, isotonic monotonicity); `ruff` and `mypy` both pass and are configured in `pyproject.toml`. |
| `BudgetLedger` not thread-safe | Medium | All mutation/reads guarded by a `threading.Lock`. |
| NaN sentinels from `reliability_bins` | Medium | Added `Bin.is_populated`; `evaluate_calibration` filters on it. |
| `evaluate_calibration` re-bins 2–3× | Medium | Refactored to bin once and derive ECE/MCE from shared bins. |
| Zero-cycle admission denial untested | Medium | `test_admission_denied_on_first_cycle_runs_nothing` (asserts `cycles_completed == 0`). |
| `configure_logging` mutates root logging | Minor | Package now installs a `NullHandler`; library never configures root implicitly. |
| `LoopContext.config: object` erased typing | Minor | Typed as `FrameworkConfig` via a `TYPE_CHECKING` import. |

Test count: 54 → 64. Coverage held at 96% branch. ruff + mypy clean.

## 8. Honest residual after revisions
- The enforced guarantee is "the **ledger** never exceeds cap and the reserve is
  never recorded into." The *real-world* cost of an over-spending runner is still
  incurred upstream — the framework stops and flags it (`overspent=True`) but
  cannot un-spend external API calls. True prevention requires the runner to
  honour `state.allowance`; the ledger makes a violation loud, not impossible.
- Property tests assert invariants, not correctness against a reference isotonic
  implementation; a port to scikit-learn's isotonic could be added as a
  differential test if exactness matters.
- All five §3 roadmap items (sanitizer, golden-set, per-domain recalibration, async loop,
  persistence) are now built and tested — §3 is empty.

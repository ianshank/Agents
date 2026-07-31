# Tasks: merge-gate-health-integrity

Ordered per `./review.md` §"Reprioritized recommendations". Owners use the fleet contract in
`openspec/AGENTS.md`. `[P]` = protected path → needs `eval-change-approved` + CODEOWNERS.
Note that `agent-core/tests/**` is itself protected (`scripts/eval_protected_paths.py:33`), so
every task below carries the label; the isolation rule is honoured by keeping `features.yaml`
and `scripts/validations/**` in their own commit. Coverage floor:
`make -C agent-core check` ≥ 95%.

## WS-B — Policy validation + operator seam (do first; WS-A depends on `cfg.n_bins`)

- [x] `GatePolicyConfig.__post_init__` bounding all nine tunables via a `_require_finite_in`
      helper (keeps the method under the mccabe 14 budget and generates interval notation).
- [x] Bounds follow one rule: reject the vacuous endpoint, allow the maximally-strict one.
      `min_auroc` strictly above 0.5 so the single-class sentinel cannot pass.
- [x] No cross-field validation — `risk_target <= 1 - wilson_floor` would reject configurations
      strictly more conservative than the defaults.
- [x] `_add_policy_args` + `_policy_from_args` on `merge_gate_ci`, defaults read off the
      dataclass so `--help` cannot drift.
- [x] Construction placed **before** the outer `except Exception -> return 1` so a bad policy
      exits 2 (usage), never 1 and never 0. Module docstring exit contract updated.
- [x] `--protected-auto-merge` deliberately omitted; `run()` warns if it is set in-process.
- [x] Tests: 22 rejection cases, 7 strict-endpoint cases, exit-2 wiring, flag-threading,
      absent-flag pin.

## WS-C — One bin count, one routing implementation

- [x] `calibration.DEFAULT_N_BINS` as the library default; `GatePolicyConfig.n_bins` as the
      tunable, passed explicitly at all three `build_domain_models` call sites.
- [x] `_bin_of` as the single score→bin router; `bin_index` and `fit` both delegate.
- [x] Store boundary floors out-of-contract scores to bin 0 and never raises (ADR 0025);
      metrics boundary keeps raising. Asymmetry pinned by test.
- [x] Edge-comparison scan retained deliberately — `min(int(raw * bins), bins - 1)` is not
      equivalent (`0.7 * 10 == 6.999999999999999`); pinned by test.
- [x] Signature test asserting all defaults resolve to `DEFAULT_N_BINS`.

## WS-A — Operating-region health measurement (centerpiece)

- [x] `_operating_bin_ci_width(scores, labels, cfg) -> float | None` replacing
      `_upper_half_ci_width`; eligibility via the Wilson **upper** bound vs `wilson_floor`.
- [x] `CalibratorHealth.bin_ci_width: float | None`; `is_trustworthy` rejects `None`.
      `None` chosen over NaN/`inf` — NaN compares False against every bound, `inf` conflates
      "not measured" with "measured as maximally wide".
- [x] `merge_gate_ci` decision line reports `bin_ci`, without which the unmeasurable state is
      invisible and no operator can tell which floor tripped.
- [x] Docstring corrections in all three places the wrong-axis claim appeared.
- [x] Tests: empty region, confidently-bad region, thin eligible bin, end-to-end
      `build_domain_models` regression, and the `== 0.0` assertion that pinned the defect
      removed.

## WS-D — Fold accounting + mutation-resistant contract test

- [x] `n = len(eval_recs)`; `n_total` added for diagnostics, gating nothing, defaulted.
- [x] Existing `n` assertions rewritten to express the contract, not the hash-derived constant.
- [x] `test_health_and_tau_are_measured_on_the_held_out_fold` — fit fold separable, held-out
      fold anti-correlated at the same scores; kills three mutants.
- [x] `outcome_labeller` precedence pinned with both signals live.
- [x] `test_run_bin_conflation_avoided` retargeted to a fold-0 id and asserted to reach the
      Wilson floor (`healthy=True`, `bin=1/1`).
- [x] Every mutation-resistance claim verified by applying the mutation and observing red.

## Ledger + decision record [P]

- [ ] ADR 0029 recording the operating-region decision and the rejected alternatives;
      pointer line added to ADR 0005.
- [ ] `features.yaml` F-ID (claimed at land) with one `verification` bullet per pinned
      invariant, each naming its proving artifact.
- [ ] `scripts/validations/F_0NN.py` — offline, text/AST-only, never imports `agent_core`
      (the validation gate installs nothing); any "CI runs X" assertion via `_common.ci_enforces`.
- [ ] CHANGELOG entry under `[1.3.0-dev]` declaring the decision-changing-when-live effects.

## Follow-on (separate change; not this one)

- [ ] Wire `.github/workflows/calibrated-merge-gate.yml` to the new policy flags via
      `vars.MERGE_GATE_*`, using the bash-array idiom. Decision-changing the moment a variable
      is set, so it needs its own review.
- [ ] Risk-appetite ADR choosing `max_bin_ci_width` / `n_bins` for activation. Under honest
      measurement the current 0.20 may require ~50+ high-accuracy audits in every eligible
      bin, which could keep the gate permanently closed — the correct default, but a human
      decision to confirm.
- [ ] G4 (widened to 4 CLIs), G6, G7, G8, G9 from the gap analysis.
- [ ] `behavioral-regression/behavioral_regression/config.py`'s `_require_positive`/
      `_require_at_least` validators have no `math.isfinite` guard — peer review of this
      change confirmed `BRConfig(dist_sigma=float("inf"))`, `BRConfig(wilson_z=float("inf"))`,
      and `BRConfig(n_pairs=float("nan"))` all construct without error. This is the exact
      failure class `GatePolicyConfig.__post_init__`'s docstring names as "already bitten by
      twice" — a third, live instance one package over, surfaced but not fixed here (a
      different package, its own protected-path review). `_require_finite_in` in
      `merge_gate.py` is the pattern to port; do not import cross-package (`agent_core` stays
      dependency-free).

## Archive

- [ ] Each F-ID lands with `status: done` + `implemented_in:<sha>`; `scripts/validate.py
      --tier fast` green; `make check-all` green; then move this change under
      `openspec/changes/archive/`.

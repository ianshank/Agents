# Changelog

All notable changes to `agent-core` are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the package follows semantic versioning.

## [Unreleased]

### Added
- **The audit-propensity contract is single-sourced** as `audit_sampler.is_valid_propensity`
  / `format_propensity` (with `PROPENSITY_PRECISION` / `PROPENSITY_UNKNOWN`). Three layers
  previously restated `0.0 < p <= 1.0` independently, and they had already drifted: only
  the store's write boundary also checked `math.isfinite`. The copies were equivalent
  solely because `0.0 < nan` happens to be `False` — true by accident, not by design.
  Rendering is shared for the same reason: the audit issue, the `gh workflow run` command
  it prints, and the recorder's log must agree, or an operator copying one into the other
  silently changes the value.

### Fixed
- **`format_propensity` could render a valid propensity into an unusable one.** Fixed-point
  (`.6f`) turned `1e-7` into `"0.000000"`, which parses back to `0.0` and is rejected by
  `is_valid_propensity`. That output is not decoration — it is pasted into the `gh workflow
  run` command the audit issue prints — so a propensity the contract accepts produced a
  dispatch guaranteed to fail at the recorder, the same failure mode the ingestion guard
  exists to prevent, one layer later. Now renders significant figures (`.6g`), which switches
  to an exponent instead of collapsing to zero and is tidier for the arithmetic-noise values
  the sampler actually emits (`0.6`, not `0.600000`). A Hypothesis property test over the
  contract's domain pins it; the previous round-trip test had hand-picked exactly the three
  values that survive.
- **Two sites bypassed the shared renderer entirely** — the `selected.txt` writer and a debug
  log. The writer is the *serialisation boundary* `audit_issue_sync` reads back, so the
  producer could emit a value its own consumer rejects. Found by running the seam end to end
  rather than trusting the unit tests, which stub it. Defining a single point of truth is not
  the same as using it, so `F_047` now fails on a local `.6f` in either module.
- **A degenerate slice reported a by-construction `AUROC = 0.5`.** `proxy_eval` computed
  AUROC whenever both outcome classes were present, even for a *constant* proxy — which
  cannot rank anything, so 0.5 is its value by construction. That is precisely the number
  `calibration_report.analyze_slice` refuses to print ("rather than a misleading AUROC of
  0.5"), in the module whose stated purpose is honesty about degeneracy. The degeneracy
  flag now gates it.
- **A tuned `lambda` could run out of residual degrees of freedom.** Charging the residual
  a second degree of freedom (correct, and what repaired small-n coverage) left `n = 2`
  with none: `_variance(..., ddof=2)` returns `0.0`, the residual term vanished, and the
  interval reported a half-width of ~0.06 from two observations. `PPIConfig` now requires
  `min_labeled >= 3` and `ppi_plus_interval` independently refuses when
  `n - resid_ddof < 1`.
- **The proxy-range check allocated two full copies of the unlabeled pool** to print one
  example; replaced by a streaming `_count_out_of_range` helper keeping only the count and
  first offender.
- `proxy_eval`'s module docstring cited `agent_core.calibration.effective_n_multiplier`;
  the symbol moved to `agent_core.ppi` in the 500-line split.

### Added
- **Proxy-correlation measurement + prediction-powered intervals (`ppi`, `proxies`,
  `proxy_eval`).** `proxy_eval` measures how well a cheap proxy predicts the authoritative
  `HUMAN_AUDIT` label — marginally *and* conditionally on the subsets the gate operates
  over (`score >= tau`, per bin) — with the implied `1/(1-rho^2)` effective-sample
  multiplier. Proxies are pluggable via a `ProxyExtractor` Protocol, so an external LLM
  judge arrives through `MappingProxy` without `agent_core` gaining a dependency.
  `ppi.ppi_plus_interval` is a power-tuned control-variate interval that reduces exactly to
  the classical estimator at `lambda = 0`, and falls back to **Wilson** (with a stated
  reason) on every path where the normal approximation cannot be trusted.
- **`OutcomeRecord.selection_propensity` + `audit_sampler.select_for_audit_detailed`.** The
  sampler now reports each pick's marginal inclusion probability and `record_verdict`
  stores it, so audits can later be reweighted (`1/p`) — a quantity that cannot be
  reconstructed once the round is over. Nullable and additive: pre-existing records load
  with `None`, and `select_for_audit` keeps its exact signature, selection and RNG order.
- **`calibration_report --estimator {wilson,ppi++}`** dual-reports both intervals plus the
  same-family classical baseline. `wilson` remains the default and the only estimator the
  gate uses.

### Fixed
- **A prediction-powered interval could render inverted (`lo > hi`) with no degeneracy
  flag.** The point estimate is unbounded above (proxy shift x lambda), and clipping `lo`
  and `hi` independently of it produced `[1.240, 1.000]` — a negative half-width and a
  point outside its own interval — printed as a trustworthy estimate. The point is now
  clamped *before* the bounds are derived, and the bounds are ordered.
- **`variance_reduction` was computed from clipped bounds, over-reporting a 3% gain as
  94%.** A ratio of `[0, 1]`-clipped widths measures proximity to a boundary, not variance:
  holding the data fixed and sliding only the unlabeled proxy mean swung the figure
  6.8% -> 93.8% -> 62.5%, though the standard error never moved. It is now derived from the
  standard errors, returns `None` when no trustworthy comparison exists, and reports a
  genuine widening as negative instead of flooring it at zero.
- **Per-bin conditional slices assumed a `[0, 1]` proxy**, silently dropping every negative
  external judge score and sweeping everything above 1.0 into a bin mislabelled `[0.9,1)`.
  Bin edges now span the observed range.
- **`build_dataset` took the *first* audit row rather than the authoritative one**,
  disagreeing with `OutcomeStore.resolved()`: an early row carrying `label=None` demoted a
  genuinely audited change into the unlabelled pool. Resolution is delegated to
  `resolved()`, which owns that precedence.
- **Small-n coverage.** `lambda` is fitted from the same points the residual variance is
  measured on, so the residual now costs a second degree of freedom (except at
  `lambda == 0`, where the estimator *is* the classical mean and the exact equivalence must
  hold). `lambda` also uses the measured unlabeled proxy variance rather than assuming it
  equals the labelled pool's.
- **`pearson_r` raised `ZeroDivisionError`** when two tiny-but-positive variances underflowed
  to zero in their product (found by the property suite); each variance is now rooted before
  multiplying. The moment helpers report an unrepresentable spread as `inf` rather than
  raising `OverflowError`.
- **`inclusion_probability`** is written `base_rate + f*(1-base_rate)` so `p >= base_rate`
  and `p <= 1` hold exactly in floating point.

### Changed
- `calibration.py` was split: prediction-powered inference moved to `ppi.py`, and the
  calibration report into `report_types.py` (shared types) + `calibration_report_render.py`
  (presentation), keeping every file inside the repo's 500-line budget. The split is
  internal — every previously importable name still resolves from its original module, and
  `calibration_report.__all__` now pins that promise.
- `domains.in_domain_scope` is the single source for `--domain-filter` classification; two
  report modules had grown byte-identical copies.

### Fixed
- **A record from a newer writer crashed every reader (ADR 0025).** `store_sync` deliberately
  preserves a line it cannot parse — "an upgraded writer during a rolling upgrade … must NOT
  crash the pipeline — and must NOT be silently dropped either" — while `jsonl` is strict
  because "an append-only audit store with a corrupt line is a store whose integrity guarantee
  is already gone". Both rationales are right, but `OutcomeRecord(**json.loads(line))` could
  not tell an **unknown extra key** from a **missing required key**: both raise `TypeError`. So
  the mechanism built to survive a rolling upgrade produced precisely the record that broke
  every other consumer — `merge_gate_ci` exiting 1 in both the gate and shadow jobs (failing
  every PR), with `outcome_labeller`, `audit_sampler`, and `merge_seed` having no handler at
  all. `OutcomeRecord.from_json` now distinguishes additive schema evolution from corruption:
  unknown fields are dropped and logged with their names, while malformed JSON, a non-object
  payload, a missing required field, and wrong types all still raise. `store_sync` is
  unchanged — it calls the constructor directly, so it still treats such a line as opaque and
  round-trips it verbatim; the writer never rewrites a field it does not understand and the
  reader no longer crashes on one. The repo already handled the *backward* direction (a
  pre-1.3.0 line without `agent_version` still loads); this closes the forward one.
- **Merge-gate fail-open: an uninterpretable confidence scored as maximum confidence.**
  `NaN` compares False against every bin edge and `inf` exceeds them all, so both fell through
  `BinningCalibrator.bin_index`'s scan to its `score >= top edge` return — the *highest*-
  confidence bucket — as did any value above 1.0. Values below 0 escalated, so the failure was
  one-sided toward unsafe: with a trustworthy calibrator, `merge_gate.decide()` returned
  `AUTO_MERGE` for both `NaN` and `5.0`. `ChangeContext` now enforces the `[0, 1]` contract its
  field comment always claimed, and `bin_index` floors any non-finite or out-of-range score to
  bin 0 — records reach it straight from the store, where `OutcomeRecord` applies no validation
  and `ChangeContext`'s check is bypassed. Exactly `1.0` is in contract and still lands in the
  top bin. Latent only because every domain is cold-start (`tau is None` without `HUMAN_AUDIT`
  records), so it would have activated exactly when the gate went live.
- **`evaluate_calibration` passed slices that cannot evidence discrimination.** An undefined
  AUROC satisfied the resolution criterion vacuously, so a forecaster wrong 100% of the time —
  perfectly calibrated against its own base rate — passed the ship gate, as did a single record.
  Degeneracy (constant predictor / single outcome class / undersized) is now always named on the
  new `CalibrationReport.degenerate` field and logged at WARNING. **Enforcement is opt-in** via
  the keyword-only `min_samples` / `require_discrimination`, surfaced as
  `CalibrationConfig.min_eval_samples` / `require_discrimination`; both default to the prior
  behaviour, so no existing caller's verdict changes and configs persisted before the fields
  existed still load and round-trip. An all-correct golden set is a legitimate shape, so it
  keeps passing until a caller opts in.
- **`merge_gate_ci` reported bad input as an internal fault.** Out-of-contract values, malformed
  JSON, a missing context field, and a `null` where a value belongs now all exit **2** (usage)
  rather than 1 — and never 0, which CI reads as proceed-to-merge. An unreadable `--context`
  path stays exit 1: the environment failing, not the caller passing a bad value.
- **`build_domain_models` decided per-domain autonomy silently.** The `HUMAN_AUDIT`-only filter
  dropped every other record with no count and no log, so an all-passive store was
  indistinguishable from an empty one. It now reports the excluded records by reason and warns
  when no audit records exist at all.

### Added
- **`subprocess_util.run_failsafe`** and **`atomic_io.atomic_write_text`** — stdlib-only shared
  utilities extracting two idioms that were duplicated and had drifted: the fail-safe subprocess
  runner (previously copied in `detectors` and `store_sync/git_sync`, the latter having lost its
  warning logs) and the atomic tmp-then-`os.replace` writer (previously copied in `persistence`
  and `store_sync/store`, the latter not logging cleanup). `detectors` and `store_sync` now bind
  `_run = run_failsafe`, preserving the `agent_core.*._run` monkeypatch seam, and the previously
  log-less paths gain observability. agent-core stays zero-runtime-dependency.

### Changed
- **`store_sync` refactored from a single module into a package** (`agent_core/store_sync/`:
  `models` / `serialization` / `store` / `git_sync` / CLI) to satisfy the ≤500-line file
  budget (ADR 0019); the previous module was 546 lines. **Non-breaking:** every previously
  importable name (the full public API plus the `_run` seam) still resolves from
  `agent_core.store_sync`, `python -m agent_core.store_sync` is unchanged, and the CLI
  monkeypatch seam is preserved byte-for-byte. The F-032 validation gate was migrated to
  grep the package's modules for the same load-bearing pieces (no check weakened).

### Added (F-032 — outcome-store persistence sync)
- `store_sync` module (ADR 0018): syncs the merge-gate outcome store with a dedicated
  git data branch (default `merge-gate-data`). `StoreSyncConfig` (all tunables; no
  literal in sync logic), injectable `GitRunner`/`Sleeper` seams, canonical
  deterministic merge (`merge_records` — full-record-JSON dedupe, total-order sort so
  `OutcomeStore.resolved()` is byte-reproducible from any interleaving), fetch-gated
  `FETCH_HEAD` reads (stale-checkout hazard), plumbing commits
  (`hash-object`/`mktree`/`commit-tree` with explicit ident — the worktree is never
  touched), bootstrap of an absent branch via a parentless root commit, and a
  bounded retry-with-backoff push loop for concurrent writers. CLI
  `python -m agent_core.store_sync {pull,push,stats}`; exit codes 0 (ok/no-op/cold
  start), 4 (fetch failed, store untouched), 5 (retries exhausted), 2 usage,
  1 internal. Unparseable / forward-incompatible store lines are preserved
  verbatim through merges (opaque lines, `_unparsed` stats key) instead of
  crashing the pipeline or being silently deleted by an older reader.
  Real-git test suite incl. Hypothesis merge properties.

### Added (F-010 — calibrated auto-merge gate, opt-in / default-off)
- `merge_gate` module: `GatePolicyConfig` (all tunables; no literal in decision logic),
  `CalibratorHealth`, `ChangeContext`, `threshold_for_risk` (risk-derived `tau` via a Wilson
  upper bound on a held-out fold), and `decide()` (mechanical-failure REJECT → protected-path
  ESCALATE → calibrated trust + per-bin Wilson floor → AUTO_MERGE).
- `outcome_store` module: append-only `OutcomeStore` (streamed line-by-line), `BinningCalibrator`
  (grouped by bin **index** so equal-accuracy bins never conflate), and `build_domain_models`
  (per-domain calibrator/health/`tau` from HUMAN_AUDIT records on a deterministic held-out fold).
- `outcome_labeller` module: passive revert / CI-failure / timeout-clean labels (alerting only;
  never feed `tau`). `audit_sampler` module: unbiased stratified sampling + authoritative
  HUMAN_AUDIT verdicts. `merge_gate_ci` module: CI entrypoint, exit codes 0/10/20 (+1 internal,
  +2 usage), decisions audit-logged.
- `detectors` module: real `GitRevertDetector` (git history), `GitHubChecksFailureAttributor`
  (GitHub Actions check-runs via `gh api`), and `resolve_repo`. Every tunable on `DetectorConfig`
  (timeouts + failing-conclusion set); all subprocess calls are timeout-bounded and fail safe.
  Replaces the previous no-op placeholder detectors wired into `outcome_labeller.main`.
- `timeutil` module: `parse_iso8601` — shared 'Z'-tolerant, UTC-defaulting ISO-8601 parser.

### Notes
- Reuses `agent_core.calibration` (`wilson_interval`, `auroc`, `expected_calibration_error`)
  rather than re-implementing the math.
- 100% coverage on the new modules; agent-core gate (ruff / ruff-format / mypy --strict /
  branch coverage ≥95%) green. Tests are mock-free (real temp git repos, real check-run payloads).

## [1.3.0] – 2026-06-20

### Added
- `OutcomeRecord.agent_version: str | None = None` — an optional keying axis used by the
  flow-calibration corpus to group outcomes by `(agent_version, domain)`. Additive and
  backwards compatible: the field defaults to `None`, so pre-1.3.0 JSONL lines (written
  without it) still load via `OutcomeRecord.from_json`. The merge gate ignores the field;
  `build_domain_models` keys by `domain` as before.

### Changed
- `SCHEMA_VERSION`/`__version__` → `1.3.0`; added the `1.2.0 → 1.3.0` config migration
  (a version-stamp only — no config section changed; the record-level default provides the
  JSONL back-compat) so configs pinned at 1.2.0 keep loading.

### Notes
- No behavior change to existing subsystems; purely an additive surface for downstream keying.
  Strict mypy + branch coverage ≥95% green.

## [1.2.0] – 2026-06-18

### Added (B1)
- `sanitize` module: `RuleSanitizer`, `Sanitizer` protocol, `SanitizationResult`, `Finding`,
  `SanitizationRule`, `build_sanitized_claims` utility.
- `SanitizerConfig` registered in `FrameworkConfig` (additive; old configs get defaults).
- `docs/sanitizer-threat-model.md` documenting covered categories and known bypasses.

### Added (B5)
- `persistence` module: `run_result_to_dict`/`from_dict`, `cycle_state_to_dict`/`from_dict`,
  `calibrator_to_dict`/`from_dict`, `save_run`, `load_run`.
- `RUN_STATE_SCHEMA_VERSION = "1.0.0"` — independent of config `SCHEMA_VERSION`.
- Calibrator serialization is behavioural: restored calibrators produce bit-identical predictions.
- Unknown-key rejection mirrors `config.from_dict` strictness.

### Added (B3)
- `recalibration` module: `TemperatureScaler` (golden-section NLL minimisation),
  `CalibratorRegistry` (fit-per-domain, freeze → read-only), `make_calibrator`,
  `CALIBRATOR_FACTORIES` (factory type `Callable[[RecalibrationConfig], Calibrator]`).
- `RecalibrationConfig` registered in `FrameworkConfig` (additive; old configs get defaults).
  All temperature constants (bracket bounds, iterations, tolerance, clamp epsilon) are config
  fields — no literals in logic.

### Added (B2)
- `golden` module: `GoldenItem`, `GoldenSet`, `GoldenSplit`, `split` (deterministic hash-bucket),
  `cohen_kappa`, `evaluate_on_split` (enforces held-out discipline in code).
- `GoldenConfig` registered in `FrameworkConfig` (additive; old configs get defaults).

### Added (B4)
- `async_loop` module: `AsyncLoopController` (async mirror of sync LoopController, disjoint),
  `ParallelClaimRunner` (semaphore-capped fan-out).
- `AsyncCycleRunner` Protocol in `protocols.py` (I/O-node seam for async verification).
- `AsyncConfig` registered in `FrameworkConfig` as `async_exec` (additive; old configs get defaults).

### Added
- Monorepo packaging: `[dev]` optional-dependencies extra, `py.typed` (PEP 561), and a
  dynamic package version single-sourced from `agent_core.version.__version__`
  (decoupled from the config `SCHEMA_VERSION`).
- Quality gates: ruff house ruleset (`E,F,W,I,N,UP,B,SIM,RUF`), `mypy --strict` on the
  library, branch-coverage gate at 95%, Hypothesis `dev`/`ci` profiles, path-scoped
  GitHub Actions CI, and a pre-commit config.
- `CONTRIBUTING.md` documenting the monorepo dev loop.

### Changed
- `selective_risk_coverage` uses `enumerate`; successive-pair assertions use
  `itertools.pairwise`; modern PEP 585/604 typing throughout.

## [1.1.0]

- Imported into the Agents monorepo. Baseline: deterministic verifier loop, per-run
  cost budget, and calibration stack; 64 tests, ~96% branch coverage.

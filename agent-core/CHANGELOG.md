# Changelog

All notable changes to `agent-core` are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the package follows semantic versioning.

## [Unreleased]

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

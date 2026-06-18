# Changelog

All notable changes to `agent-core` are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the package follows semantic versioning.

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

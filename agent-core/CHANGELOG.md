# Changelog

All notable changes to `agent-core` are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the package follows semantic versioning.

## [Unreleased]

### Added (B1)
- `sanitize` module: `RuleSanitizer`, `Sanitizer` protocol, `SanitizationResult`, `Finding`,
  `SanitizationRule`, `build_sanitized_claims` utility.
- `SanitizerConfig` registered in `FrameworkConfig` (additive; old configs get defaults).
- `docs/sanitizer-threat-model.md` documenting covered categories and known bypasses.

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

> Phase B features (sanitizer, golden-set, per-domain recalibration, async loop,
> persistence) will append their entries here per PR.

## [1.1.0]

- Imported into the Agents monorepo. Baseline: deterministic verifier loop, per-run
  cost budget, and calibration stack; 64 tests, ~96% branch coverage.

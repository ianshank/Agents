# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Quality & Eval-Integrity Gates

### Added
- **Calibrated auto-merge gate (F-010, opt-in / default-off):** a pure `agent_core`
  subsystem — `merge_gate.py` (deterministic `decide()`: mechanical-failure REJECT →
  protected-path ESCALATE → risk-derived `tau` + calibrator health + Wilson bin floor →
  AUTO_MERGE), `outcome_store.py` (append-only `OutcomeStore`, `BinningCalibrator`, and
  per-domain models built from HUMAN_AUDIT records on a held-out fold), `outcome_labeller.py`
  (passive revert/CI-failure/timeout-clean signals), `audit_sampler.py` (unbiased stratified
  sampling), and `merge_gate_ci.py` (CI entrypoint, exit codes 0/10/20, audit-logged
  decisions). Wired via `.github/workflows/calibrated-merge-gate.yml`, which auto-merges
  nothing unless `ENABLE_CALIBRATED_AUTOMERGE` is set. Documented in ADR 0005. Strict mypy +
  100% module coverage.
- **Real outcome detectors (F-010):** `outcome_labeller` wires real detectors instead of
  no-op placeholders — `agent_core/detectors.py`: `GitRevertDetector` (reads `git log` for
  the `This reverts commit <sha>` footer), `GitHubChecksFailureAttributor` (a commit's GitHub
  Actions check-runs via `gh api`), and `resolve_repo`. Every tunable lives on `DetectorConfig`
  (timeouts + failing-conclusion set); all subprocess calls are timeout-bounded and fail *safe*
  (missing binary / timeout / no repo → "no signal observed"). Shared `agent_core/timeutil.py`
  (`parse_iso8601`, Z-tolerant, UTC-default). Tests are mock-free — real temporary git
  repositories and real check-run payloads.

### Fixed
- **Calibrated merge gate (review follow-ups):** `calibrated-merge-gate.yml`'s decide step
  now fails on `REJECT` *and* on `merge_gate_ci`'s internal-error (`1`) / usage (`2`) exit
  codes — previously only `20` mapped to failure, so an error silently passed the gate.
  `OutcomeStore.all()` streams the append-only JSONL line-by-line instead of `read_text()`-ing
  the whole (unbounded) store into one string.
- **architecture-drift-guard:** `migrate_to_current` rejects a non-string
  `schema_version` (e.g. YAML list/dict) with a `ManifestError` instead of a bare
  `TypeError`; `_prepend_sys_path` now preserves manifest `sys_path` order on
  `sys.path` (was reversed by repeated `insert(0, …)`). (PR review follow-ups.)

### Changed
- **`validate_skill.py` (all copies):** the eval `setup` command's exit code is no
  longer ignored — a non-zero `setup` now fails the eval (with truncated
  stdout/stderr) instead of silently poisoning a passing run. Applied byte-identically
  to the canonical `scripts/validate_skill.py` and all three vendored skill copies.

### Added
- **Regression Gate (F-006):** `scripts/regression_gate.py` — materialises an isolated
  HEAD baseline via `git worktree` and blocks only *net-new* ruff/offline-test failures,
  complementing the absolute coverage gate. Line-keyed lint identity, robust class-based
  junit nodeid reconstruction, configurable lint/test paths + base ref + `block`/`warn`
  mode, and a JSON report validated by `scripts/regression_report.schema.json`.
- **Eval-Integrity Protected-Path Guard (F-007):** `scripts/eval_protected_paths.py`
  (single source of truth + glob matcher) and `scripts/check_protected_changes.py` CI
  guard, backed by `.github/CODEOWNERS`, require human approval (the `eval-change-approved`
  label) for any change to evaluation-defining files (features, config, gating, scorers,
  judges, validations, tests, CI).
- **Auto-Fix Loop — design-only, disabled (F-008):** `scripts/fix_loop.py` inert skeleton
  with a path-traversal-safe `ScopeGuard` that cannot write to protected paths, plus
  `docs/decisions/0004-auto-fix-loop.md` and the human enable-checklist.
- **Quality-Gates Workflow:** `.github/workflows/quality-gates.yml` runs feature
  validation, a dedicated ≥85% coverage gate for the new tooling, the regression gate
  (vs the PR base), and the protected-path guard.
- **Architecture Drift-Guard Skill (F-009):** `skills/architecture-drift-guard/` — a
  self-contained skill (runtime deps `grimp` + `pyyaml` only) that extracts a codebase's
  actual Python import graph, folds it to C4 **components**, and diffs it against a
  declared `architecture.yaml`. `scripts/drift_check.py` is the deterministic drift gate
  (with `--emit-actual` to bootstrap a manifest); `scripts/mermaid_gen.py` renders the C4
  diagram and `--check` enforces freshness. Reusable `scripts/adguard/` library with the
  grimp call isolated in `extractor.py`; ≥90% unit coverage plus structural+behavioral evals.
- **Architecture Dogfood Gate:** root `architecture.yaml` + `architecture.mmd` (seeded from
  `--emit-actual` and reviewed) and `.github/workflows/architecture-drift.yml`, a
  deterministic drift+freshness gate over `eval_harness` and `agent_core`. No model is in
  the gate's decision path.

### Changed
- **`.gitignore` / `.dockerignore`:** Ignore `regression_report.json`,
  `.regression_gate_junit.xml`, and the merge-gate runtime artifacts
  `merge_outcomes.jsonl` / `merge_decisions.jsonl`.
- **`tests/conftest.py`:** Expose `scripts/` on `sys.path` so tooling has first-class tests.
- **README / C4 Architecture:** Document the quality-gate and eval-integrity layer.
- **`skills CI` workflow:** Added an isolated `architecture-drift-guard` job (matrix
  3.10–3.12, pinned `grimp==3.14`) that never installs the repo packages.
- **`pyproject.toml`:** Added the pinned `archguard` optional extra used by the dogfood gate.

### Security
- Hardened `ScopeGuard` against path-traversal / absolute-path escapes (per peer review):
  writes are confined to the project root *and* outside the protected set.

## [1.1.0] — 2026-06-16

### Added
- **Skill Framework (F-003, F-004):** `scripts/validate_skill.py` tiered validation engine
  with structural + behavioral checks and `evals.json`-driven assertions.
- **OpenAI Judge Skill (F-004):** Full `skills/openai-judge/` skill with SKILL.md, eval
  fixtures, and a CLI runner supporting NVIDIA Nemotron & LM Studio backends.
- **Langfuse Tracing (F-005):** End-to-end Langfuse integration — `SDKLangfuseClient`,
  `observe()` decorator, `SafeLangfuseContext`, trace-to-dataset-item linking, and
  auto-wrapping of OpenAI client via `langfuse.openai`.
- **Spec-driven Development (F-001):** `validate.py`, `select_next.py`, `features.yaml`,
  `features.schema.json`, and per-feature validation scripts.
- **ADR Documents:** `0001-openai-compatible-judge.md`, `0002-skill-framework.md`,
  `0003-langfuse-integration.md`.
- **Snyk Integration:** Project registered for continuous dependency monitoring. `.snyk`
  policy file and `requirements.txt` manifest added.
- **`.dockerignore`:** Keeps container images lean.
- **C4 Architecture Diagram:** `docs/c4_architecture.md` — Mermaid-based context, container,
  and component views.

### Changed
- **`.gitignore`:** Expanded to cover `.coverage.*` shards, `.env` files, IDE artifacts,
  OS files, Snyk policy, and benchmark/output directories.
- **`README.md`:** Updated to reflect Langfuse, Snyk, OpenAI judge, and skill framework.
  Added architecture section, environment variable reference, and CI integration guide.
- **`pyproject.toml`:** Added `[tool.ruff]` and `[tool.mypy]` configuration sections.
  Added `ruff`, `mypy` to dev dependencies.

### Fixed
- **Security (CRITICAL):** Removed hardcoded Langfuse API keys from
  `langfuse_client/__init__.py`. Credentials are now sourced exclusively from
  environment variables or explicit kwargs.
- **Security:** Removed `pragma: no cover` from `SDKLangfuseClient` — the class is
  exercised by mocked tests and should contribute to coverage.
- **Testing:** Replaced `os.environ.clear()` in `test_langfuse_integration.py` with
  `monkeypatch` — fixes 24 cascading test failures on Windows due to destroyed
  `ComSpec` / `SystemRoot` variables.
- **Testing:** Rewrote `test_langfuse_integration.py` from `unittest.TestCase` to
  idiomatic `pytest` style with `monkeypatch` for environment isolation.
- **Config Loader:** Added `encoding="utf-8"` to `config/__init__.py` `load_config()`
  to fix silent encoding errors on Windows (`cp1252` default).
- **Logging:** Replaced f-string logger calls with lazy `%s` formatting in `judges/`
  and `langfuse_client/` to avoid unnecessary string interpolation.

### Security
- **Snyk Scan:** 9 dependency vulnerabilities identified (4 High in `urllib3`, 5 Medium).
  Documented in `CHANGELOG.md` and `requirements.txt` with minimum safe versions.

## [1.0.0] — 2026-06-15

### Added
- Initial release: spec-driven evaluation harness.
- Core modules: `engine.py`, `cli.py`, config loader with env interpolation and
  schema migrations.
- Component registries: scorers, datasets, targets, sinks, judges.
- Built-in scorers: `exact_match`, `regex_match`, `contains`, `json_keys`, `llm_judge`.
- Built-in datasets: `inline`, `jsonl`, `langfuse`.
- Built-in targets: `echo`, `callable` (dynamic import).
- Built-in sinks: `console`, `json_file`, `langfuse`.
- Built-in judges: `mock`, `bedrock`, `openai`.
- Quality gating with configurable rules.
- Entry-point plugin discovery.
- ~96% test coverage, 86 tests.

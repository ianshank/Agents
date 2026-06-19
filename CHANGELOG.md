# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`py.typed` marker (PEP 561):** `src/eval_harness/py.typed` shipped and registered
  in `pyproject.toml` — downstream type-checkers now recognise the package as typed.
- **Configurable `OpenAIJudge` parameters:** `stream`, `failure_score`,
  `retry_attempts`, `retry_wait_multiplier_seconds`, `retry_wait_min_seconds`,
  `retry_wait_max_seconds`, and `langfuse_openai_module` are now constructor
  arguments with sensible defaults, enabling per-instance tuning and full unit-test
  coverage of retry/failure paths.
- **`BedrockJudge.anthropic_version`:** Configurable Bedrock API version string
  (default `"bedrock-2023-05-31"`).
- **Named constants in `judges/__init__.py`:** Magic numbers and string literals
  extracted to module-level constants (`DEFAULT_OPENAI_MAX_TOKENS`, etc.).
- **`BedrockJudge` test suite (`tests/test_bedrock_judge.py`):** Full mocked-boto3
  coverage of request construction, response parsing, and custom `score_field`.

### Changed
- **`agent_core_adapter`:** Import guard for `agent_core.protocols` now uses a
  `TYPE_CHECKING` branch so mypy sees the real types without a hard runtime import;
  falls back to a lazy `import_module` at runtime.
- **CI (`eval-harness-ci.yml`):** `pytest` step now enforces `--cov-fail-under=96`
  to lock in the improved coverage baseline.
- **Input validation:** `OpenAIJudge.__init__` validates `max_tokens`, `temperature`,
  `top_p`, `failure_score`, retry bounds, `score_field`, and `langfuse_openai_module`
  at construction time.

### Tests
- **Coverage gaps closed (gating, sinks, judges):** Added 18+ new test cases across
  `test_components.py`, `test_engine.py`, and `test_openai_judge.py` to exercise
  previously uncovered branches:
  - `ConsoleSink` verbose mode output
  - `LangfuseSink` no-client guard, `min_value_to_log` filter
  - `evaluate_gate` with `pass_rate=None` and `max`-constraint violations
  - `OpenAIJudge` empty-choices chunk, non-rate-limit API errors, no-JSON / malformed-JSON
    response paths, `attach_client()` with `SDKLangfuseClient`, and Langfuse import failure
  - `BedrockJudge` request body, response parsing, custom score field
- **`pragma: no cover`:** Annotated the unreachable `ImportError` branch in
  `judges/__init__.py` (openai is a required extra; the branch cannot be hit when
  the package is correctly installed); removed the blanket annotation from `BedrockJudge`
  class now that it is covered by mocked tests.
- Overall line coverage: **93.8% → 96.49%**. All 152 tests pass.

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

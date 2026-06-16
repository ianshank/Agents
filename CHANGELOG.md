# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

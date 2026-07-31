# Changelog

All notable changes to `behavioral-regression` are documented here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/); the package
follows semantic versioning, and `SCHEMA_VERSION` (the persisted-config schema)
is tracked separately from the distribution version in
`behavioral_regression/version.py`.

## [Unreleased]

### Added
- `CHANGELOG.md` — this file, bringing the package in line with its siblings
  (`agent-core`, `flow-corpus`, `flow-protocol`) which each ship a changelog.
- Apache-2.0 `LICENSE` and packaging metadata (`license`, `[project.urls]`,
  `classifiers`, `readme`) in `pyproject.toml`.

## [0.1.0] – 2026-06

### Added
- The calibrated, offline **behavioral-regression detector** (ADR 0006): given
  two model versions, decide whether v2 has drifted (e.g. become more
  sycophantic) relative to v1, and emit a **ship / hold / escalate** verdict.
- Composition over the sibling packages — reuses `agent_core` calibration
  primitives and `flow_corpus` oracle/bootstrap primitives rather than
  reimplementing them; the cross-package contract flows through `flow-protocol`.
- **Fail-safe-to-escalate** semantics: when the detector cannot prove its own
  judgement is trustworthy (cold start, insufficient signal), it escalates rather
  than silently shipping.
- A CLI entry point (`[project.scripts]`) for running the gate.
- Config is versioned and auto-migrated (`behavioral_regression.version`); every
  threshold lives in a validated `*Config` field (no hard-coded values).

### Notes
- Deterministic and offline: the suite runs with no network and no live SDKs.
- Branch coverage gated at 95%; strict mypy on the library.

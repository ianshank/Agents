# Changelog

All notable changes to `flow-protocol` are documented here. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the package follows semantic versioning, and
`PROTOCOL_VERSION` (the wire-contract semver) is tracked separately from the distribution version.

## [1.0.0] – 2026-06-20

### Added
- The versioned contract surface shared across the corpus/harness airgap (F-011): frozen
  Pydantic v2 models `FlowResult`, `OracleResult`, and `ConfidenceChannel`. `raw_confidence`
  is optional (outcome-only flows need not fabricate one); `OracleResult.verdict` is
  `bool | None` where `None` denotes an indeterminate (abstained) verdict.
- `PROTOCOL_VERSION` (initial `1.0.0`) and a `migrate_protocol` migration chain mirroring
  `agent_core.version`, so future additive contract bumps stay backwards compatible.
- `ConfidenceChannel.per_step` enforces each value in `[0, 1]` via a field validator.

### Notes
- The only dependency is `pydantic>=2`. 100% test coverage; strict mypy. This package is the
  sole import surface permitted across the airgap — it must never depend on the corpus or harness.

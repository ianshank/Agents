# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Component names (skills, subagents, hooks) are append-only within a major version.

## [Unreleased]

## [1.0.0] - 2026-07-03

### Added

- Plugin manifest and self-hosted marketplace (`.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`); plugin name `foundation`, namespace `foundation:*`.
- Four skills, each with `evals/evals.json` (skill-creator format, ≥3 cases):
  `foundation:plan`, `foundation:code-review`, `foundation:test-first`,
  `foundation:c4-docs`.
- Two least-privilege subagents: `explorer` (read-only scanner) and `test-runner`
  (isolated verification loop).
- Three hooks sharing `hooks/_lib.py`: `pre-tool-guard` (PreToolUse, fails closed),
  `post-edit-verify` (PostToolUse, fails open), `session-logger` (JSONL audit, fails
  open); env-var configuration via `CLAUDE_FOUNDATION_LOG_DIR`,
  `CLAUDE_FOUNDATION_GUARD_DENY_GLOBS`, `CLAUDE_FOUNDATION_VERIFY_CMD`.
- MCP template `.mcp.json.example` with env-var placeholders (no live servers).
- `foundation_tools` Python package: pinned doc-derived schemas (`schemas.py`),
  frontmatter/manifest validator (`validate.py`), no-hardcode scanner (`scan.py`),
  skill-creator eval-gate wrapper (`eval_gate.py`), JSONL logging (`jsonlog.py`).
- CI pipeline: deterministic merge gate per PR (`claude plugin validate`, ruff, mypy,
  validator, scanner, pytest, install smoke test) and release gate on tags (eval gate,
  backwards-compat fixture).
- Documentation: README quickstart, C4 architecture diagrams, ADRs 0001-0003,
  pinned sources provenance record.

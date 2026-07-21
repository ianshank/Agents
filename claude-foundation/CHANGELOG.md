# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Component names (skills, subagents, hooks) are append-only within a major version.

## [Unreleased]

### Added

- `foundation_tools.backwards_compat`: implements ADR 0001 pt. 4's append-only
  component-name contract (ADR 0004). Diffs live skill/agent/hook names against a
  checked-in `tests/backwards_compat_baseline.json`; fails the release gate on a
  removal without a corresponding major version bump, never on additions. `--update`
  regenerates the baseline pre-release. Wired into the `release-gate` CI job
  alongside `eval_gate`.

### Changed

- `foundation:plan`, `foundation:test-first`, `foundation:code-review`: contract
  amendments teaching each skill to consume a committed quality-gate script when the
  target project has one (`scripts/quality-gate.sh` with
  `lint|typecheck|test|coverage|all`, or a Makefile `check` target delegating to it).
  `plan` phrases success criteria and the feedback loop as gate subcommand invocations
  (inventing parallel tool commands while a gate exists is treated as fabrication) and
  reads enforced lint/style constraints from the gate's `do_*` functions; `test-first`
  takes the test framework from the gate's test step and delegates suite-wide runs to
  `./scripts/quality-gate.sh test`/`coverage` while the red phase deliberately stays
  test-scoped; `code-review` asks callers to run `./scripts/quality-gate.sh all`
  beforehand and pass its output in as evidence (the fork remains read-only), with
  deterministic scanners owning regex-detectable secrets/hardcoded values and the
  review hunting semantic ones. When no gate exists, all three skills derive commands
  from the repository as before. Evals extended with one gate-routing case per skill.
- `foundation:c4-docs` contract: recognizes manifest-owned component views.
  Discovery (step 1) now also looks for a repo-root manifest declaring
  components/dependencies with a deterministic generator and CI drift gate;
  Level 3 (step 5) must reference such a generated artifact instead of
  hand-inferring a diagram at the manifest's granularity (hand-written L3 only
  below the manifest's resolution, never contradicting it); drift handling
  (step 8) forks by coverage — for gate-covered artifacts, run the host's
  drift check, surface undocumented edges, and route the intended-vs-mistake
  decision to the user, never editing the manifest or generated diagram
  unilaterally; uncovered levels keep the existing flag-and-update behavior.
  Two eval cases added covering the reference-don't-redraw and
  drift-routed-to-user paths.

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

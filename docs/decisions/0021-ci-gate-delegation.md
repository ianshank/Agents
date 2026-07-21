# 0021 — CI Gate Delegation Strategy

- Status: **Proposed.**
- Date: 2026-07-20
- Related: `.github/workflows/agent-core-ci.yml`, `.github/workflows/eval-harness-ci.yml`,
  `.github/workflows/flow-corpus-ci.yml`, `.github/workflows/behavioral-regression-ci.yml`,
  `.github/workflows/claude-foundation-ci.yml`, `.github/workflows/skills-ci.yml`,
  `.github/actions/run-quality-gate/action.yml`, ADR 0020 (deterministic generator skills).

## Context

Following the implementation of ADR 0020 (Deterministic generator skills), the repository gained the ability to generate deterministic, byte-stable quality-gate scripts (`quality-gate.sh`) and Makefiles. The repo dogfoods these generators, resulting in localized quality-gate scripts and a root/per-package `Makefile` layout.

However, the repository's own continuous integration (CI) workflows (`.github/workflows/*.yml`) did not adopt these generated gates. Instead, they duplicate the environment setup, ruff check, ruff format check, mypy execution, and pytest invocations directly inline within YAML step definitions. This duplication introduces a maintenance burden:
1. **Local vs CI Drift**: Any adjustment to lint targets, package paths, coverage thresholds, or tool arguments must be updated in both the local generated scripts/Makefiles and the GitHub Actions workflows.
2. **Boilerplate**: A single workflow like `skills-ci.yml` repeats identical python-setup and validation blocks for 7 different skills, resulting in a large, redundant configuration file (~252 lines).
3. **Execution Inconsistency**: Local checks running through `make check` or `scripts/quality-gate.sh` can diverge from the validation checks enforced by GitHub Actions blockers.

## Decision

We will delegate CI quality-gate verification to the generated `quality-gate.sh` scripts (or their corresponding `Makefile` wrappers) across all package-level and skill-level CI pipelines. 

1. **Establish a Reusable Composite Action**: Implement `.github/actions/run-quality-gate/action.yml` to encapsulate standard dependencies (python, ruff, mypy, pytest) and orchestrate execution.
2. **Rewire Package-level Workflows**:
   - `agent-core-ci.yml`
   - `eval-harness-ci.yml`
   - `flow-corpus-ci.yml`
   - `behavioral-regression-ci.yml`
   - `claude-foundation-ci.yml`
   All of these will call the composite action targeting their local `Makefile` or `quality-gate.sh`.
3. **Rewire Skill-level Workflows**:
   - `skills-ci.yml` will be updated so each skill job delegates setup and validation to the local skill check targets.
4. **Exclusions**: Scheduled, dispatch-only, or system-level workflows with specialized integration logic (e.g., `merge-gate-verdict.yml`, `phoenix-live.yml`, `outcome-labeller.yml`) are not governed by the local quality-gate scripts and will continue using inline specialized steps.

## Consequences

- **Local-CI Convergence**: Running verification locally using `make check` will run the exact same steps, configurations, and checks as CI.
- **Redundancy Reduction**: Standardizes the toolchain installation and execution, saving approximately 400 lines of duplicated GitHub workflow definitions.
- **Improved Maintainability**: Changes to testing or linting behavior are made once in the local configuration or generator script and are instantly active in CI.
- **Tooling dependency**: CI runners will require standard tools like GNU Make and bash, which are already standard across default GitHub Actions runners (e.g., `ubuntu-latest`).

## Alternatives Considered

- **Keep Inline Steps**: Keep CI workflows hand-maintained and separate. Rejected because it directly contradicts the ADR 0020 design law: *"CI runs the same quality-gate.sh — so local == CI by construction, not by discipline."*
- **Call `quality-gate.sh` directly without Make**: While possible, calling `make check` preserves the uniform developer interface both locally and in CI. The action will support direct script execution where appropriate.

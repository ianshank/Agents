# Epic 3: Monorepo & CI Infrastructure

## Focus Area
Multi-package architecture, CI/CD pipeline automation, type-checking fortification, cross-platform compatibility, and architectural drift prevention.

## Landed Features & Milestones
- **[x] Five-Package Monorepo Topology**: Clean separation across `eval_harness`, `agent_core`, `flow_protocol`, `flow_corpus`, and `behavioral_regression`.
- **[x] Public Surface Compatibility Guards (F-039)**: Byte-identical `test_public_surface.py` across all packages, freezing public API exports.
- **[x] Operational Scripts Quality Gates (F-031)**: Dedicated coverage and lint gates for scripts under `scripts/`.
- **[x] CI Gate Delegation (ADR 0021)**: Composite action `.github/actions/run-quality-gate` unifying local `make check` and CI workflows.
- **[x] Charter Invariant & Drift Enforcement**: `scripts/check_charter_invariants.py` and `scripts/check_charter_drift.py` guarding architectural claims.
- **[x] Cross-Platform Portability Hardening**: WMI interpreter shim for Windows (`sitecustomize.py`), path normalization, and cross-platform E2E test matrix.
- **[x] Nightly E2E CI Workflow**: `.github/workflows/nightly-e2e.yml` running the complete monorepo test suite across Python 3.11, 3.12, 3.13 daily.

## In Progress & Planned
1. **Full `mypy --strict` Over Root `tests/`**:
   - Clean up remaining bare generics and untyped helper functions in legacy test files.
2. **Branch Protection Quality Gates**:
   - Wire `quality-gates.yml` and invariant checks to required status checks.
3. **Single-Instrumented Coverage Runs**:
   - Combine test execution with multi-pass coverage reporting to halve CI wall-clock time.

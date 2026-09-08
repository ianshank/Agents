# Workspace Engineering & Testing Standards

## 1. Core Invariants & Architecture

- **No Hardcoded Values:** No hardcoded secrets, absolute paths, URLs, or numeric magic numbers at call sites. All tunables belong in typed dataclasses or `.env`.
- **500-Line Size Budget:** Production code modules must remain strictly under 500 lines (ADR 0019). Test files must remain under 700 lines.
- **Strict Typing:** All modules must pass `python -m mypy`. Avoid `Any` where protocols or explicit types exist.
- **Pinned Toolchains:** `ruff==0.15.20`, `mypy==2.1.0`. Never run bare tools from PATH that may shadow pinned venv dependencies.

## 2. Testing Discipline & Zero-Skip Policy

- **Zero Unapproved Skips:** Tests must never be loosened, modified, or skipped with `pytest.skip()` without an explicit, active waiver in `skip-waivers.json`.
- **Structural DI Mocks:** Components that communicate with external APIs (judges, datasets, sinks) must use structural Protocol mocks (`MockJudge`, `echo` target, `MappingEvidenceStore`) for offline testing.
- **Deterministic Trajectories:** Tool-call canonicalization and outputs must produce byte-identical, deterministic results across random seeds (`PYTHONHASHSEED`).

## 3. Platform & Windows Portability

- Inject `scripts/e2e_shims/sitecustomize.py` into `PYTHONPATH` to prevent WMI query deadlocks on Windows hosts.
- Always use byte I/O or `.as_posix()` paths to prevent CRLF line-ending corruption in git trees and cross-platform drift.

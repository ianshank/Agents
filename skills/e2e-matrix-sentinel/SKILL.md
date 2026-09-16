---
name: e2e-matrix-sentinel
version: 1.0.0
description: Validate cross-platform end-to-end matrix coverage, verify POSIX and Windows driver parity, and enforce offline fixture restamping invariants. Use whenever running end-to-end matrix suites, checking e2e driver parity, or validating matrix coverage freshness.
---

# E2E Matrix Sentinel — Cross-Platform E2E & Matrix Coverage Guard

The `e2e-matrix-sentinel` guarantees driver parity, registry matrix completeness, and artifact freshness across Windows and POSIX environments.

## Invariants

1. **Driver Parity (Derive-Never-Allowlist)**: `scripts/run_all_e2e.sh` and `scripts/run_all_e2e.ps1` must declare the exact same set of steps. Any step added to one driver without the other violates cross-platform CI safety.
2. **Matrix Coverage Freshness**: `docs/matrix-coverage.md` must match `python tests/test_matrix_coverage.py --check` at all times.
3. **Offline Restamping Separation**: Live E2E runs (such as `docs/e2e-live-journey.md`) must never be used to restamp offline evaluation fixtures or 0–10 score cells (`OfflineRestampConfig`).

## Usage

### Run All Sentinel Checks
```bash
python skills/e2e-matrix-sentinel/scripts/sentinel.py --check
```

### Verify Driver Parity Specifically
```bash
python -m pytest tests/test_e2e_driver_parity.py -v
```

### Check Matrix Completeness & Coverage Freshness
```bash
python tests/test_matrix_coverage.py --check
```

## Definition of Done

- Driver parity between `run_all_e2e.sh` and `run_all_e2e.ps1` is 100% verified.
- `docs/matrix-coverage.md` is fresh and conforms to the plugin registry census.
- Sentinel CLI passes with exit code 0.

# 0024 - Assertion Graders Registry and Skill Validation Alignment

**Status**: Accepted  
**Date**: 2026-07-23  

## Context and Problem Statement
The skill script validation mechanism (`scripts/validate_skill.py`) previously routed structural assertions through a monolithic `if/elif` chain. As new behaviors and assertions were introduced, the cyclomatic complexity (e.g. `ruff C901`) scaled unmanageably. Additionally, we enforce byte-for-byte identical syncing of `validate_skill.py` across all vendor skill directories (`skills/*/scripts/validate_skill.py`). Updating a single hard-coded dictionary or if/elif check became a maintenance bottleneck.

## Decision
We extracted the monolithic assertion routing into an `ASSERTION_GRADERS` registry map. Each assertion type is now assigned a dedicated grader function (e.g., `grade_exit_zero`, `grade_output_contains`). 

We establish the following extensibility contract for the multi-copy `validate_skill.py` script:
1. **Registry Pattern**: All assertions must be graded dynamically by fetching the corresponding function from the `ASSERTION_GRADERS` dictionary map.
2. **Deterministic Outputs**: The `grade_idempotent` strategy and others must exclusively rely on deterministic fields (e.g. comparing only `stdout` instead of combining `stdout` with `stderr`, as `stderr` can emit spurious network logging that fails idempotency checks).
3. **Canonical Synchronization**: Enhancements or additions of new assertion handlers MUST be performed exclusively in `scripts/validate_skill.py` and synced symmetrically down to all `skills/<skill>/scripts/validate_skill.py`. The `check_skill_script_drift.py` gate guards this constraint.

## Consequences
- **Positive**: We completely eliminated `C901` cyclomatic complexity. Future additions of grader functions are inherently isolated and unit-testable.
- **Positive**: Type hints and behavior match deterministically.
- **Negative**: Adds minor indirection for evaluating tests.

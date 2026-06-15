# ADR-0002 — Reusable Skill Template and E2E Skill Validator

**Status:** accepted

**Context:**
To support structured, spec-driven development of LLM capability skills, we need a standard format for skill documentation (`SKILL.md`) and an automated validation runner to verify that skills produce the expected outputs on real inputs (behavioral testing) without code duplication.

**Decision:**
1. Adopt the `SKILL_TEMPLATE.md` structure defining Preconditions, Procedure, Output contract, and Failure handling.
2. Build a project-level `scripts/validate_skill.py` command-line utility capable of performing structural verification (checking for required headers, name/trigger formats) and behavioral validation (running task commands against fixtures under `.skill-validation/` and verifying output assertions).
3. Distribute a copy of `validate_skill.py` into each skill's `scripts/` folder to match the bundled layout spec.
4. Run python commands in the validation assertions rather than Unix-dependent bash commands to guarantee cross-platform compatibility on Windows, macOS, and Linux.

**Consequences:**
- Skills are fully self-contained and testable.
- Development of new evaluation capabilities follows a strict "spec-first, validate E2E" pipeline.
- Requires standard Python testing environment (pytest, pyyaml).

**Related features:**
- F-003, F-004

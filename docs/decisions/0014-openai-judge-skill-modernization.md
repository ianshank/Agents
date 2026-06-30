# 0014 — openai-judge skill modernization (uniform v2.0 convention)

- Status: **Accepted.** Convention alignment; the skill's runtime behaviour is unchanged.
- Date: 2026-06-30
- Related: ADR 0002 (skill framework), F-023 (skill marketplace), F-028,
  `skills/openai-judge/`, `scripts/validate_skill.py`.

## Context

`openai-judge` was the first skill and the last one still on the original convention.
The newer skills (`eval-corpus-forge`, `architecture-drift-guard`) added a `tests/`
directory, a `validator_version` frontmatter key, and a `ruff.toml`, plus a per-skill CI
job. `openai-judge` had none of these — its runner had no unit tests at all, so the
"every skill is self-validating and coverage-gated" property had a hole.

## Decision

1. **Adopt the v2.0 layout** for `openai-judge` without changing what the skill does:
   - Add `validator_version: '2.0'` to the `SKILL.md` frontmatter and bump `version`
     `1.0.0 → 1.1.0` (the marketplace registry entry is bumped in lock-step; the F-023
     semver-match rule is enforced by `scripts/skill_marketplace.py validate`).
   - Add `skills/openai-judge/ruff.toml` (`extend = "../../pyproject.toml"`), excluding the
     vendored `scripts/validate_skill.py` (which the skill-script drift guard pins to the
     canonical copy, so its style is owned upstream).
   - Add `skills/openai-judge/tests/` (`conftest.py` + `test_run.py`) exercising
     `scripts/run.py`: the `--mock` path, the input-file-error path, and the live path via a
     **fake `eval_harness.judges` injected into `sys.modules`** — no real SDK, no network.
     Coverage on the runner is ≥95% (only the `__main__` guard is uncovered).
   - Add a `.gitignore` for `.skill-validation/` artefacts.
2. **Add an `openai-judge` job** to `.github/workflows/skills-ci.yml`, mirroring the other
   skills' jobs (isolated install of `pytest`/`pytest-cov`/`ruff`, lint, coverage-gated
   tests, then `validate_skill.py --tier structural,behavioral`). The job is isolated: the
   runner's tested paths need no repo packages.
3. **Reuse the validator read-only.** F-028's own validator imports
   `parse_frontmatter`/`check_structural` from the canonical `scripts/validate_skill.py`
   without modifying it, so the drift guard is unaffected.

## Consequences

- **No behaviour change.** `run.py`'s logic is unchanged (only import-ordering / `open()`
  mode lint fixes). Existing configs and the live API path are untouched.
- **Uniform skill bar.** All three skills now carry tests, a coverage gate, a ruff config,
  `validator_version`, and a CI job — the convention is no longer aspirational.
- **Tested offline.** `scripts/validations/F_028.py` asserts the frontmatter, the new files,
  structural validity, and the marketplace version match; the skill's own
  structural+behavioral evals (all `--mock`) still pass.

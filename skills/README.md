# skills/

A **schema-validated marketplace** of local, reusable [Claude Code
skills](https://docs.claude.com/en/docs/claude-code) used by this repository.
Each skill is self-contained (its own `SKILL.md` spec, scripts, and evals) and is
indexed in [`marketplace.yaml`](marketplace.yaml) (schema:
[`marketplace.schema.json`](marketplace.schema.json)).

Note: skills use a `SKILL.md` spec file, **not** a `README.md` — that is the
skill convention, distinct from the rest of the repo. This file is the overview
the marketplace itself doesn't provide.

## Registered skills

| Skill | Ver | What it does |
|---|---|---|
| [`openai-judge`](openai-judge/) | 1.1.0 | LLM-as-a-judge evaluations over OpenAI-compatible APIs |
| [`architecture-drift-guard`](architecture-drift-guard/) | 1.0.0 | Detect and block architecture drift in CI against a declared C4 component model |
| [`eval-corpus-forge`](eval-corpus-forge/) | 1.0.0 | Build, validate, and package reusable evaluation datasets |
| [`model-bench`](model-bench/) | 1.0.0 | Benchmark and A/B-test multiple LLMs on one dataset |
| [`project-setup`](project-setup/) | 1.1.0 | Generate a deterministic Makefile from a project's detected toolchain |
| [`quality-gate`](quality-gate/) | 1.1.0 | Generate a deterministic lint + type + test + coverage gate script |
| [`deploy`](deploy/) | 1.0.0 | Generate a safety-railed deployment script (dry-run / confirm / rollback) |
| [`dataset-lint`](dataset-lint/) | 1.0.0 | Validate eval datasets for structure, duplicate IDs, and encoding |

## Two kinds of skill

- **Inference skills** consume a model (e.g. `openai-judge`, `model-bench`).
- **Deterministic generator skills** (`project-setup`, `quality-gate`, `deploy`)
  emit committed artifacts (Makefiles, gate scripts) and contain **no**
  model-backed logic — see [ADR 0020](../docs/decisions/0020-deterministic-generator-skills.md)
  and [ADR 0022](../docs/decisions/0022-determinism-boundary-for-inference-skills.md)
  for the determinism boundary.

## Working with skills

```bash
# Validate the whole registry (versions match SKILL.md frontmatter; each skill
# passes structural + behavioral validation):
python scripts/skill_marketplace.py validate
python scripts/skill_marketplace.py list

# Validate a single skill's structure and behavior:
python scripts/validate_skill.py skills/<name>
```

`scripts/validate_skill.py` is duplicated byte-identically into each
`skills/<skill>/scripts/` (so every skill stays self-contained) and is
drift-guarded by `scripts/check_skill_script_drift.py` — if you edit the canonical
copy, re-sync the vendored copies.

## Adding a skill

1. Scaffold from [`docs/SKILL_TEMPLATE.md`](../docs/SKILL_TEMPLATE.md) (and
   [`docs/SKILL_VALIDATION_TEMPLATE.md`](../docs/SKILL_VALIDATION_TEMPLATE.md)).
2. Add an entry to `marketplace.yaml` with a semver `version` matching the
   `SKILL.md` frontmatter.
3. Run `python scripts/skill_marketplace.py validate`.

Skills are exercised in CI by `.github/workflows/skills-ci.yml` (pinned
`ruff`/`mypy` + `pytest --cov-fail-under=95`).
